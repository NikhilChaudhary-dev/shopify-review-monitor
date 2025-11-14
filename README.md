Shopify Review Monitor

This script monitors a specific Shopify app page for new 1-star or 2-star reviews and sends a notification to Slack when one is found.

This guide focuses on setting up the script to run automatically using GitHub Actions.

GitHub Actions Setup (Automatic & Free)

This is the most reliable method and works even when your computer is off.

Step 1: Create a GitHub Repository

Go to GitHub.com and log in.

Click the "+" icon in the top-right corner and select "New repository".

Give it a name (e.g., shopify-review-monitor).

You can keep it Public or Private (both will work with GitHub Actions).

Click "Create repository".

Step 2: Upload Your Files

On your new repository page, click the "Add file" > "Upload files" button.

You need to upload 3 files from your project folder:

main.py

requirements.txt

.github/workflows/monitor.yml

IMPORTANT: For the monitor.yml file, you must first create the folders.

On the GitHub page, click "Add file" > "Create new file".

In the name box, type .github/workflows/monitor.yml. (Typing the / will create the folders).

Paste the content of your monitor.yml file into the editor.

Click "Commit changes".

Step 3: Add Your Slack Webhook as a Secret

This is the most important step. We must securely store your Slack URL.

In your new GitHub repository, click on the "Settings" tab.

On the left menu, go to "Secrets and variables" > "Actions".

Click the "New repository secret" button.

In the Name box, type exactly: SLACK_WEBHOOK_URL

In the Secret box, paste your full Slack Webhook URL (the one that starts with https://hooks.slack.com/...).

Click "Add secret".

Step 4: Run Your First Test

The script is now set to run automatically on the schedule (4 times a day). If you want to test it right now:

Click on the "Actions" tab at the top of your repository.

On the left, click on "Shopify Review Monitor".

You will see a message: "This workflow has a workflow_dispatch event...". Click the "Run workflow" button on the right.

A pop-up will appear. Just click the green "Run workflow" button.

You can now click on the running job to watch its progress live. On this first run, it will create the review_state.json file and commit it to your repository. On all future runs, it will use this file to check for new reviews.
