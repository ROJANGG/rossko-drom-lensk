name: Update Rossko photos

on:
  workflow_dispatch:
    inputs:
      limit:
        description: "How many new products to scan in this run. Use 5000 for autopilot."
        required: true
        default: "5000"
      start:
        description: "Use auto to continue from input/photo_progress.txt, or enter a number manually."
        required: true
        default: "auto"
      workers:
        description: "Parallel workers. 8 is safe default, 12 is faster."
        required: true
        default: "8"
      sleep:
        description: "Pause between request submissions. 0 is fastest."
        required: true
        default: "0"
      verify_images:
        description: "true = slower extra image checks, false = fast mode"
        required: true
        default: "false"
  schedule:
    # UTC. Runs every 2 hours and continues from input/photo_progress.txt.
    - cron: "17 */2 * * *"

permissions:
  contents: write

concurrency:
  group: rossko-photos
  cancel-in-progress: false

jobs:
  update-photos:
    runs-on: ubuntu-latest

    steps:
      - name: Checkout repository
        uses: actions/checkout@v4

      - name: Set up Python
        uses: actions/setup-python@v5
        with:
          python-version: "3.11"

      - name: Install dependencies
        run: python -m pip install --upgrade pip && python -m pip install -r requirements.txt

      - name: Resolve scan settings
        id: scan
        run: |
          LIMIT="${{ github.event.inputs.limit }}"
          START="${{ github.event.inputs.start }}"
          WORKERS="${{ github.event.inputs.workers }}"
          SLEEP="${{ github.event.inputs.sleep }}"
          VERIFY_IMAGES="${{ github.event.inputs.verify_images }}"

          if [ -z "$LIMIT" ]; then LIMIT="5000"; fi
          if [ -z "$START" ] || [ "$START" = "auto" ]; then
            if [ -f input/photo_progress.txt ]; then
              START="$(cat input/photo_progress.txt | tr -dc '0-9')"
            else
              START="0"
            fi
          fi
          if [ -z "$START" ]; then START="0"; fi
          if [ -z "$WORKERS" ]; then WORKERS="8"; fi
          if [ -z "$SLEEP" ]; then SLEEP="0"; fi
          if [ -z "$VERIFY_IMAGES" ]; then VERIFY_IMAGES="false"; fi

          echo "limit=$LIMIT" >> "$GITHUB_OUTPUT"
          echo "start=$START" >> "$GITHUB_OUTPUT"
          echo "workers=$WORKERS" >> "$GITHUB_OUTPUT"
          echo "sleep=$SLEEP" >> "$GITHUB_OUTPUT"
          echo "verify_images=$VERIFY_IMAGES" >> "$GITHUB_OUTPUT"

          echo "Photo scan settings: start=$START limit=$LIMIT workers=$WORKERS sleep=$SLEEP verify_images=$VERIFY_IMAGES"

      - name: Find Rossko photos
        run: |
          ARGS=(
            --limit "${{ steps.scan.outputs.limit }}"
            --start "${{ steps.scan.outputs.start }}"
            --workers "${{ steps.scan.outputs.workers }}"
            --sleep "${{ steps.scan.outputs.sleep }}"
            --progress-file "input/photo_progress.txt"
          )
          if [ "${{ steps.scan.outputs.verify_images }}" != "true" ]; then
            ARGS+=(--no-verify-image)
          fi
          python update_photos_rossko.py "${ARGS[@]}"

      - name: Generate Drom price file
        run: python update_prices.py

      - name: Commit updated files
        run: |
          git config user.name "github-actions[bot]"
          git config user.email "41898282+github-actions[bot]@users.noreply.github.com"
          git add input/photos.csv input/photo_progress.txt input/rossko_price.xlsx public/drom_lensk.xlsx logs/updates.log
          if git diff --cached --quiet; then
            echo "No changes to commit"
          else
            git commit -m "Update Rossko photos"
            git push
          fi
