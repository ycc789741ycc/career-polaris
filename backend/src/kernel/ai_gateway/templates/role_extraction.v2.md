expected_output_tokens: 1800
You name a group of job postings and pull out what the group requires.

Rules:
- `name` is one job title a hiring manager would recognise, e.g. "Senior
  Backend Engineer". Not a description, not a sentence, and not a name for a
  group ("... Roles", "... Positions").
- `name` is the job only. Leave out where or how it is worked (Remote,
  Hybrid, On-site, a city or a country), gender or equal-opportunity tags
  such as "(m/f/x)", and company, team or product names, even when every
  posting carries them. The postings' locations are shown so you can read
  them, not so you name the role after them.
- Requirements are free text statements taken from the postings themselves.
  Do not score them against any person; you have not been shown one.
- `weight` is 0.0-1.0: how consistently the requirement appears across these
  postings. Something in every posting is 1.0.
- `expected_level` is one of: familiar, proficient, advanced, expert.
- Produce between 5 and 12 requirements. Merge near-duplicates.
- If the postings are too mixed to be one role, say so in `is_coherent: false`
  and still give the best name you can.

Reply with only a JSON object of this shape:
{"name": "...", "is_coherent": true,
 "requirements": [{"statement": "...", "weight": 0.0, "expected_level": "..."}]}
---
Job postings in this group:
{{postings}}
