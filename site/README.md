# Morrow Site

Edit `index.html`, `styles.css`, and article files under `posts/`. New posts should start from `article-template.html`, not from scratch.

Validate the site before publishing:

```bash
python3 tools/validate_site.py
```

Then publish from the repo root with:

```bash
./tools/deploy-site.sh
```

The deploy script now runs the validator automatically. It will fail if:

- a post drifts away from the shared article shell,
- a post adds inline styles outside the allowed score-bar custom property,
- a post or homepage link points at a missing local file,
- an image is missing alt text.

This syncs the site to `s3://morrow.run/` and invalidates the CloudFront distribution for `morrow.run` and `www.morrow.run`.
