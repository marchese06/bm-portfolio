name: Generate Daily Note

on:
  schedule:
    # 9:00am ET = 13:00 UTC
    - cron: '0 13 * * 1-5'
  workflow_dispatch:

permissions:
  contents: write
  models: read

jobs:
  generate:
    runs-on: ubuntu-latest
    steps:
      - name: Checkout repo
        uses: actions/checkout@v4

      - name: Set up Python
        uses: actions/setup-python@v5
        with:
          python-version: '3.11'

      - name: Install dependencies
        run: pip install requests

      - name: Generate daily note
        env:
          GITHUB_TOKEN: ${{ secrets.GITHUB_TOKEN }}
        run: python generate_daily_note.py

      - name: Commit and push daily_note.json
        run: |
          git config user.name "github-actions[bot]"
          git config user.email "github-actions[bot]@users.noreply.github.com"
          git add daily_note.json
          git diff --staged --quiet || git commit -m "Daily note $(date -u '+%Y-%m-%d %H:%M UTC')"
          git push
