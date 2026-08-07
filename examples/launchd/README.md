# Lifehug launchd jobs

These examples run one persistent local worker plus the canonical daily,
weekly, and monthly entry scripts. Every real script invocation only enqueues
work; `system/jobs.py worker` is the sole local writer.

1. Copy the four `*.plist.example` files to `~/Library/LaunchAgents/` without
   the `.example` suffix.
2. Replace every `<FRAMEWORK_ROOT>` and `<VAULT_ROOT>` with absolute paths.
   They may be different: executable assets come from the framework root and
   `state/jobs/` always lives inside the vault root.
3. Provide Telegram/API secrets through your normal private launchd
   environment. Never put them in a committed plist.
4. Validate and load each file:

   ```bash
   plutil -lint ~/Library/LaunchAgents/com.lifehug.worker.plist
   launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.lifehug.worker.plist
   launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.lifehug.daily.plist
   launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.lifehug.weekly.plist
   launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.lifehug.monthly.plist
   ```

The schedules use local machine time: daily at 09:00, weekly Sunday at 20:00,
and monthly on day 1 at 21:00. Edit `StartCalendarInterval` before loading if
needed. The scripts deduplicate ordinary scheduler retries by date/week/month.
After an ambiguous failure of a non-idempotent delivery, inspect its
metadata-only record with `python3 system/jobs.py show <job-id>`; it is never
blindly replayed.

To unload an example, use `launchctl bootout gui/$(id -u) <plist-path>`.
