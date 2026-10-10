"""Composition root.

The only place that knows about every module at once. Modules are wired here
and handed their collaborators; none of them reaches for another's internals.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from decimal import Decimal
from functools import lru_cache, partial

from advisor.activity import ActivityService
from advisor.assessment import AssessmentService, create_assessment_service
from advisor.gapfill import GapFillService, create_gapfill_service
from advisor.gapplan import GapPlanService, create_gapplan_service
from advisor.identity import (
    AuthService,
    GoogleEndpoints,
    GoogleOidc,
    GoogleSignIn,
    IdentityService,
    create_auth_service,
    create_identity_service,
)
from advisor.market import FreshWindows, MarketService, create_market_service
from advisor.profile import (
    AtlassianAccountReporter,
    GitHubConnector,
    JiraConnector,
    OAuthTokenRefresher,
    ProfileService,
    create_profile_service,
)
from advisor.resume import ResumeService, create_resume_service
from advisor.rolemap import RoleMapService, create_rolemap_service
from advisor.target import TargetService, create_target_service
from kernel.ai_gateway import AiGateway
from kernel.auth import ALGORITHM, JwksResolver, StaticSecretResolver, TokenVerifier
from kernel.config import Settings, get_settings, must
from kernel.db import Database
from kernel.limits import Limiter, SpendMeter
from kernel.presence import PresenceView, get_presence
from kernel.storage import ObjectStore
from wiring.limits import Limits, create_limits
from wiring.platform_ai import PlatformSpendMeter

# Google rotates its signing keys over days; an hour keeps the fetch rare while
# a newly published key is still picked up well before it is used.
_GOOGLE_KEYS_CACHE_SECONDS = 3600


@dataclass
class Container:
    settings: Settings
    database: Database
    identity: IdentityService
    auth: AuthService
    profile: ProfileService
    market: MarketService
    rolemap: RoleMapService
    assessment: AssessmentService
    target: TargetService
    gapfill: GapFillService
    gapplan: GapPlanService
    resume: ResumeService
    activity: ActivityService
    object_store: ObjectStore
    limiter: Limiter
    limits: Limits
    # None while the platform's AI key is off (ADR 0064).
    platform_spend: PlatformSpendMeter | None
    _verifier: TokenVerifier | None = None
    _google: GoogleSignIn | None = None

    @property
    def verifier(self) -> TokenVerifier:
        """Built on first use.

        Only `api` verifies tokens, so the worker runs with no signing secret
        at all and must not fail for wanting one.
        """
        if self._verifier is None:
            settings = self.settings
            self._verifier = TokenVerifier(
                issuer=settings.auth_token_issuer,
                audience=settings.auth_token_audience,
                resolver=StaticSecretResolver(settings.require_auth_secret()),
                algorithms=(ALGORITHM,),
            )
        return self._verifier

    async def get_presence(self) -> PresenceView:
        """Whether the worker and the crawler are up (ADR 0052)."""
        return await get_presence(
            self.database, away_after_seconds=self.settings.presence_away_after_seconds
        )

    @property
    def google_sign_in(self) -> GoogleSignIn | None:
        """Google sign-in, or None when it is not configured.

        Built on first use, like the verifier: only `api` signs anyone in.
        """
        settings = self.settings
        if not settings.google_sign_in_enabled:
            return None
        if self._google is None:
            api_base = must(settings.auth_public_api_base_url, "AUTH_PUBLIC_API_BASE_URL")
            endpoints = GoogleEndpoints(
                authorize_url=must(
                    settings.google_oauth_authorize_url, "GOOGLE_OAUTH_AUTHORIZE_URL"
                ),
                token_url=must(settings.google_oauth_token_url, "GOOGLE_OAUTH_TOKEN_URL"),
                client_id=must(settings.google_oauth_client_id, "GOOGLE_OAUTH_CLIENT_ID"),
                client_secret=must(
                    settings.google_oauth_client_secret, "GOOGLE_OAUTH_CLIENT_SECRET"
                ).get_secret_value(),
                redirect_uri=f"{api_base.rstrip('/')}/api/v1/auth/google/callback",
            )
            provider = GoogleOidc(
                endpoints,
                keys=JwksResolver(
                    must(settings.google_oauth_jwks_url, "GOOGLE_OAUTH_JWKS_URL"),
                    cache_seconds=_GOOGLE_KEYS_CACHE_SECONDS,
                ),
                timeout_seconds=settings.crawl_http_timeout_seconds,
                user_agent=settings.service_name,
            )
            self._google = GoogleSignIn(self.auth, provider, secret=settings.require_auth_secret())
        return self._google

    async def aclose(self) -> None:
        await self.database.dispose()


def build(settings: Settings | None = None) -> Container:
    settings = settings or get_settings()
    database = Database(settings)
    object_store = ObjectStore(settings)

    default_cap = Decimal(str(settings.ai_default_monthly_budget_usd))
    identity = create_identity_service(database, default_monthly_cap_usd=default_cap)

    # Only the api signs tokens; the worker never does, so the secret is
    # resolved lazily rather than at wiring time.
    auth = create_auth_service(
        database,
        secret=settings.auth_jwt_secret.get_secret_value() if settings.auth_jwt_secret else "",
        issuer=settings.auth_token_issuer,
        audience=settings.auth_token_audience,
        access_ttl_seconds=settings.auth_access_token_ttl_seconds,
        refresh_ttl_days=settings.auth_refresh_token_ttl_days,
        default_monthly_cap_usd=default_cap,
    )

    # identity supplies the gateway's credential and budget ports, which is how
    # the kernel stays free of any domain import.
    platform_spend = (
        PlatformSpendMeter(SpendMeter(database), settings) if settings.platform_ai_enabled else None
    )
    gateway = AiGateway(
        settings=settings, credentials=identity, budget=identity, platform_spend=platform_spend
    )

    profile = create_profile_service(
        database,
        object_store=object_store,
        connectors={
            "github": GitHubConnector(must(settings.github_api_base_url, "GITHUB_API_BASE_URL")),
            "jira": JiraConnector(must(settings.jira_api_base_url, "JIRA_API_BASE_URL")),
        },
        # GitHub's OAuth-app tokens never expire; Atlassian's last an hour.
        token_refreshers={
            "jira": OAuthTokenRefresher(
                "jira",
                jira_oauth_base=must(settings.jira_oauth_base_url, "JIRA_OAUTH_BASE_URL"),
                client_id=must(settings.jira_oauth_client_id, "JIRA_OAUTH_CLIENT_ID"),
                client_secret=must(
                    settings.jira_oauth_client_secret, "JIRA_OAUTH_CLIENT_SECRET"
                ).get_secret_value(),
            ),
        },
        resume_max_bytes=settings.resume_max_bytes,
        resume_max_pages=settings.resume_max_pages,
        http_timeout_seconds=settings.crawl_http_timeout_seconds,
        user_agent=settings.service_name,
        # Atlassian's personal data report (ADR 0061); off while no owner is named.
        account_reporter=AtlassianAccountReporter(
            must(settings.jira_api_base_url, "JIRA_API_BASE_URL")
        ),
        reporting_owner_id=settings.jira_reporting_owner_id,
    )
    market = create_market_service(
        database,
        windows=FreshWindows(
            search=timedelta(hours=settings.market_search_fresh_hours),
            board=timedelta(hours=settings.market_board_fresh_hours),
        ),
    )
    rolemap = create_rolemap_service(
        database,
        market=market,
        gateway=gateway,
        embedding_model=settings.embedding_model_name,
        top_k=settings.role_map_top_k,
        candidate_count=settings.role_candidate_count,
    )
    assessment = create_assessment_service(
        database,
        profile=profile,
        rolemap=rolemap,
        gateway=gateway,
        confidence_threshold=settings.assessment_confidence_threshold,
        candidate_count=settings.role_candidate_count,
    )
    target = create_target_service(
        database,
        assessment=assessment,
        rolemap=rolemap,
        object_store=object_store,
        upload_max_bytes=settings.own_posting_max_bytes,
        upload_max_pages=settings.own_posting_max_pages,
    )
    gapfill = create_gapfill_service(database, target=target, profile=profile, gateway=gateway)
    gapplan = create_gapplan_service(
        database,
        target=target,
        profile=profile,
        assessment=assessment,
        rolemap=rolemap,
        gapfill=gapfill,
        gateway=gateway,
    )
    resume = create_resume_service(
        database,
        target=target,
        profile=profile,
        assessment=assessment,
        gapfill=gapfill,
        gateway=gateway,
        object_store=object_store,
        template_max=settings.resume_template_max,
        template_upload_max_bytes=settings.template_upload_max_bytes,
        template_upload_max_pages=settings.template_upload_max_pages,
    )

    activity = ActivityService(
        profile=profile,
        assessment=assessment,
        rolemap=rolemap,
        get_presence=partial(
            get_presence, database, away_after_seconds=settings.presence_away_after_seconds
        ),
        stale_after_seconds=settings.job_stale_after_seconds,
    )

    return Container(
        settings=settings,
        database=database,
        identity=identity,
        auth=auth,
        profile=profile,
        market=market,
        rolemap=rolemap,
        assessment=assessment,
        target=target,
        gapfill=gapfill,
        gapplan=gapplan,
        resume=resume,
        activity=activity,
        object_store=object_store,
        limiter=Limiter(database),
        limits=create_limits(settings),
        platform_spend=platform_spend,
    )


@lru_cache(maxsize=1)
def container() -> Container:
    return build()
