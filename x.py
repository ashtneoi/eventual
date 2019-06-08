#!/usr/bin/env python3


import json
import os
import time
from sys import stderr

import requests

from eventual import (
    Actor,
    Event,
    event_input,
    EventOutput,
    LogEvent,
    Manager,
    Timer,
)


GITHUB_REF_REQUEST_FORMAT = "".join("""
{{
  repository(owner: "{owner}", name: "{name}") {{
    ref(qualifiedName:"{ref_name}") {{
      target {{
        oid
      }}
    }}
  }}
}}
""".splitlines()).replace("\n", "")


def ensure_trailing_newline(x):
    if x[-1] != '\n':
        return x + '\n'
    else:
        return x


class GetGitHubRef(Actor):
    commit_id = EventOutput()

    def __init__(self, mgr, repo_owner, repo_name, ref_name):
        super().__init__(mgr)
        self.repo_owner = repo_owner
        self.repo_name = repo_name
        self.ref_name = ref_name

    @event_input
    def trigger(self, _ev):
        r = requests.post(
            'https://api.github.com/graphql',
            headers={
                'authorization': f'token {os.environ["GITHUB_AUTH"]}',
                'content-type': 'application/json',
            },
            data=json.dumps({
                "query": GITHUB_REF_REQUEST_FORMAT.format(
                    owner=self.repo_owner,
                    name=self.repo_name,
                    ref_name=self.ref_name,
                ),
            }),
        )
        now = time.monotonic()
        if not r.ok:
            stderr.write(ensure_trailing_newline(r.text))
            r.raise_for_status()
        self.commit_id(Event(
            r.json()['data']['repository']['ref']['target']['oid'],
            now,
        ))


if __name__ == '__main__':
    mgr = Manager()

    t = Timer(mgr, 10)

    log1 = LogEvent(mgr)
    log1.attach(event_in=t.trigger)

    g = GetGitHubRef(mgr, "ashtneoi", "eventual", "refs/heads/master")
    g.attach(trigger=log1.event_out)

    log2 = LogEvent(mgr)
    log2.attach(event_in=g.commit_id)

    mgr.start()
    mgr.run()
