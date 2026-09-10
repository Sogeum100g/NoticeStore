"""Legacy module retained so older imports fail harmlessly.

Notification delivery is now driven by per-subscription crawl-result events in
``celery_app.process_notification_event``. There is no user-selected-time task.
"""
