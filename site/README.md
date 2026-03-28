# Morrow Site

Edit `index.html` and `styles.css`, then publish from the repo root with:

```bash
./tools/deploy-site.sh
```

This syncs the site to `s3://morrow.run/` and invalidates the CloudFront distribution for `morrow.run` and `www.morrow.run`.
