#!/usr/bin/env python3

from eventual import (
    Manager,
    IntervalTimer,
    LogEvent,
)


if __name__ == '__main__':
    mgr = Manager()
    t = IntervalTimer(mgr, 2)
    l = LogEvent(mgr)
    t.attach(trigger=l.event_in)
    t.active(True)
    mgr.run()
