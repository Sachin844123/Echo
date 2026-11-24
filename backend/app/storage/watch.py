"""Read Windows watchdog events without walking new directories in its emitter."""

import os
from pathlib import Path

from watchdog.observers.api import EventQueue, ObservedWatch


class Notifications(EventQueue):
    def __init__(self, notify):
        super().__init__()
        self.notify = notify

    def put(self, item, block=True, timeout=None):
        event, _watch = item
        self.notify(Path(event.src_path), event.event_type == "created")


def windows_watch(root: Path, notify):
    if os.name != "nt":
        raise OSError("watch_unavailable")
    from watchdog.events import FileCreatedEvent, FileModifiedEvent
    from watchdog.observers.read_directory_changes import WindowsApiEmitter

    class FlatEmitter(WindowsApiEmitter):
        def queue_events(self, timeout):
            # The pinned Windows emitter otherwise walks every added directory,
            # before the application has had a chance to apply its exclusions.
            try:
                events = self._read_events()
            except OSError:
                self.stop()
                return
            for event in events:
                if event.is_removed_self:
                    self.queue_event(FileModifiedEvent(self.watch.path))
                    self.stop()
                    break
                changed = FileCreatedEvent if event.is_added or event.is_renamed_new else FileModifiedEvent
                self.queue_event(changed(os.path.join(self.watch.path, event.src_path)))

    emitter = FlatEmitter(Notifications(notify), ObservedWatch(str(root), recursive=True))
    emitter.start()
    return emitter
