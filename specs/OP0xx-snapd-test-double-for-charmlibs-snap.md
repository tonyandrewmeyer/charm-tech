# OP???: snapd test double for charmlibs.snap

| Field | Value |
| --- | --- |
| Status | Draft |
| Type | Implementation |
| Created | 30 Jul 2026 |

## Abstract

`charmlibs.snap` 2.0 talks to snapd over a unix socket. There’s no snapd on a test runner, so the first `charmlibs.snap` call in a machine charm’s test raises `snap.ConnectionError`, and the charm errors out before it gets to anything the test wanted to check. At the moment the only way around that is to monkeypatch the library.

This spec proposes `Snapd`, a stateful fake snapd that replaces the library’s client functions and leaves the rest of the library running as it does in production. A test sets up what’s installed (and, if it cares, what’s in the store), runs the charm, and then checks what’s installed now and what the charm asked snapd to do:

```python
from charmlibs import snap_testing


def test_install_handler(snapd):
    ctx = ops.testing.Context(PrometheusCharm)
    state_out = ctx.run(ctx.on.install(), ops.testing.State())

    assert snapd.installed['prometheus'].channel == '2/stable'
    assert state_out.unit_status == ops.ActiveStatus()
```

The double is `charmlibs.snap`’s testing package, `charmlibs-snap-testing`. It implements OP093’s `mocked()`, which OP089’s `Juju` uses to pick it up. There’s a working implementation (see [Further Information](#further-information)).

## Rationale

`charmlibs.snap` is a set of module-level functions (`ensure_installed`, `install`, `refresh`, `remove`, `hold`, `start`, `stop`, `get`, `set`, `connect`, `alias`, `logs`, and so on), and they all send their requests through a small private client module that speaks JSON to `/run/snapd.socket`.

What charms do today is monkeypatch the public functions in each test (for example, [osquery-operator](https://github.com/canonical/osquery-operator/blob/2e0810a8153a5cfe99392f0d18797a32aa1d7b59/tests/unit/test_osquery.py#L20-L33)):

```python
def test_install(monkeypatch):
    monkeypatch.setattr(snap, 'ensure_installed', lambda *a, **kw: True)
    ctx.run(ctx.on.install(), ops.testing.State())
```

This gets the test running, but it checks very little. A charm that calls `snap.ensure_installed('prometheus', '2/stable', 7)` passes, even though the real library raises `TypeError` (`revision` is keyword-only), and the same goes for a snap name the library would reject with `ValueError`. The stub has no state, so there’s no way to test a charm that installs something and then reads it back. Each charm also ends up writing its own version of the stub, and they tend to cover less as they get copied around.

The most valuable tests are often the ones a stub like this can’t express at all: snapd not being reachable, a snap that isn’t in the store, or a `post-refresh` hook failing part of the way through a refresh.

## Specification

### Packaging

The double is a separate distribution, `charmlibs-snap-testing`, in the `charmlibs` monorepo at `snap/testing/`. It follows the layout and version lock from OP077, and the API from OP093. It would be the first testing package for a library that isn’t an interface library.

A charm adds the `testing` extra to its test dependencies, which keeps the two versions in step:

```toml
[dependency-groups]
unit = [
    "charmlibs-snap[testing]",
    "ops[testing]",
    "pytest",
]
```

and imports it as:

```python
from charmlibs import snap_testing
```

It depends on `charmlibs-snap` (at the same version) and nothing else. The OP077 template also has `ops[testing]`, because interface testing packages return stand-in charms (OP093’s `provider` and `requirer`). A fake snapd doesn’t return anything from ops, and leaving ops out means it works under `ops.testing`, under `Harness`, or with no ops at all.

Installing the package registers a `snapd` pytest fixture through a `pytest11` entry point, so there’s nothing to add to `conftest.py`.

The double patches functions in the library’s private `_client` module, even though it’s a separate distribution (see [Alternatives](#alternatives) for why). `charmlibs.snap` should document that `charmlibs-snap-testing` relies on those functions, so that they aren’t changed without updating the double.

### The API

Here’s everything the package exports, all from `charmlibs.snap_testing`:

```python
class Snapd:
    def __init__(
        self,
        installed: Iterable[Snap] = (),
        *,
        store: Iterable[StoreSnap] | None = None,
        connections: Iterable[Connection] = (),
        failures: Iterable[Failure] = (),
    ): ...

    # A context manager: entering patches charmlibs.snap's client, and exiting the
    # outermost `with` puts it back.
    def __enter__(self) -> Snapd: ...
    def __exit__(self, *exc_info) -> None: ...

    installed: Mapping[str, Snap]  # What's on the machine now.
    connections: frozenset[Connection]
    history: Sequence[Operation]  # What the charm did, in order.


def mocked() -> ContextManager[Snapd]: ...  # OP093's mocked().


# These are frozen dataclasses. The revision is stored as a string, as snapd reports it.
class Snap:
    def __init__(
        self,
        name: str,
        *,
        channel: str = 'latest/stable',
        revision: int | str = 1,
        version: str = '1.0',
        classic: bool = False,
        hold: datetime.datetime | None = None,
        services: Mapping[str, Literal['active', 'inactive']] = {},
        config: Mapping[str, Any] = {},
        aliases: Mapping[str, str] = {},  # Maps each alias to its app.
        logs: Iterable[snap.LogEntry] = (),
    ): ...


class StoreSnap:
    def __init__(
        self,
        name: str,
        *,
        channels: Mapping[str, int] = {'latest/stable': 1},  # Maps each channel to its revision.
        version: str = '1.0',
        classic: bool = False,
        services: Iterable[str] = (),
        daemon_services: Iterable[str] = (),  # Enabled and started on install.
    ): ...


class Connection:
    def __init__(self, plug: tuple[str, str], slot: tuple[str, str]): ...  # (snap, name) pairs.


class Failure:
    def __init__(
        self,
        action: str,  # 'install', 'refresh', 'set', and so on, or '*' for everything.
        *,
        snap: str | None = None,  # None means any snap.
        error: snap.Error,
        times: int | None = None,  # None means every time.
    ): ...


class SnapStateValidationError(Exception): ...
```

The `Operation` subclasses that go in `history` are listed in [Checking what the charm did](#checking-what-the-charm-did).

There’s also the `snapd` fixture, which is a fresh, empty `Snapd` that’s open for the whole test.

### Where the double intercepts

Entering a `Snapd` replaces the four functions in `charmlibs.snap._client` that do I/O (`get`, `get_logs`, `post`, and `put`) with an in-memory model of the snapd REST endpoints the library uses. Leaving it puts the originals back.

The rest of the library runs unchanged, including `ensure_installed`’s logic for deciding whether to install or refresh, validating snap names, normalising and resolving channels, parsing `InstalledInfo`, and turning snapd’s error kinds into the library’s exceptions (including the extra requests the library makes to tell `NotInstalledError` and `NotInStoreError` apart). So a charm test exercises the same library code that runs on a real machine.

The library’s own unit tests already patched these four functions, with canned responses written out for each test. The difference here is that the responses come from a model that changes as the charm acts.

A `Snapd` is reentrant, as OP093 requires: the fixture and the test that uses it can both open it, and `Juju` can open `mocked()` inside it. It’s single-use, though. Opening it again after its outermost `with` has finished raises `RuntimeError`, so state can’t leak from one test into the next:

```python
def test_fixture_and_with_block_nest(snapd):
    with snapd:  # The fixture already opened it, so this just nests.
        snap.ensure_installed('prometheus', '2/stable')
    assert snapd.installed['prometheus'].channel == '2/stable'


def test_reentry_after_exit_raises():
    snapd = snap_testing.Snapd()
    with snapd:
        pass
    with pytest.raises(RuntimeError):
        with snapd:
            pass
```

### Setting up the machine

If the starting state doesn’t matter, the fixture gives an empty machine with no store described, so any snap can be installed from any channel:

```python
def test_workload_manager(snapd):
    workload.reconcile(channel='2/edge')
    assert snapd.installed['prometheus'].channel == '2/edge'
```

When it does matter, pass the installed snaps to `Snapd`. They’re the same frozen `Snap` objects that `installed` gives back, so a test can describe the state it expects at the end in the same terms it used for the start:

```python
def test_config_changed_refreshes_channel():
    snapd = snap_testing.Snapd([
        snap_testing.Snap(
            'prometheus', channel='2/stable', revision=100, services={'prometheus': 'active'}
        ),
    ])
    ctx = ops.testing.Context(PrometheusCharm)

    with snapd:
        ctx.run(ctx.on.config_changed(), ops.testing.State(config={'channel': '2/edge'}))

    assert snapd.installed == {
        'prometheus': snap_testing.Snap(
            'prometheus', channel='2/edge', revision=100, services={'prometheus': 'active'}
        ),
    }
```

This kind of whole-state comparison works because every value the double fills in itself is fixed and documented. With no store, an install gets revision `'1'` and version `'1.0'`, and a refresh keeps the current revision unless the charm asked for a specific one. (Whether a refresh happened at all is something to check in `history`, below.)

Snap configuration, holds, aliases and logs are all part of `Snap`:

```python
def test_config_round_trip():
    snapd = snap_testing.Snapd([
        snap_testing.Snap('grafana', config={'http.port': 3000}),
    ])
    ctx = ops.testing.Context(GrafanaCharm)

    with snapd:
        ctx.run(ctx.on.config_changed(), ops.testing.State(config={'port': 8080}))

    assert snapd.installed['grafana'].config == {'http.port': 8080}
```

```python
def test_logs():
    when = datetime.datetime(2026, 11, 23, 9, 0, tzinfo=datetime.timezone.utc)
    snapd = snap_testing.Snapd([
        snap_testing.Snap(
            'prometheus',
            services={'prometheus': 'active'},
            logs=[
                snap.LogEntry(when, 'prometheus.prometheus', 1234, 'Server is ready'),
            ],
        ),
    ])

    with snapd:
        entries = snap.logs('prometheus')

    assert [e.message for e in entries] == ['Server is ready']
```

Interface connections are passed separately, since a connection belongs to two snaps:

```python
def test_disconnect():
    plug = ('telegraf', 'system-observe')
    snapd = snap_testing.Snapd(
        [snap_testing.Snap('telegraf'), snap_testing.Snap('core')],
        connections=[snap_testing.Connection(plug=plug, slot=('core', 'system-observe'))],
    )

    with snapd:
        snap.disconnect(plug)

    assert snapd.connections == set()
```

A snap installed with no store described has no services, so `start`, `stop` and `restart` raise `AppNotFoundError` for it, as they would on a real machine for a service the snap doesn’t ship. That’s stricter than a lot of tests need, but if the double made up services, a charm that starts the wrong service would still pass, which is one of the bugs the monkeypatched version misses too:

```python
def test_service_not_shipped():
    with snap_testing.Snapd([snap_testing.Snap('prometheus')]):
        with pytest.raises(snap.AppNotFoundError):
            snap.start('prometheus', 'prometheus')
```

To test a charm that manages services, give the snap some with `services=` on the `Snap`, as in the earlier examples, or describe the store (see the next section).

`Snapd` checks what it’s given when it’s constructed, much like Scenario’s consistency checker, so a starting state that real snapd could never be in fails immediately with `SnapStateValidationError`, not with something confusing several calls later. That includes malformed snap names and channels, the same snap listed twice, an alias for an app the snap doesn’t have, a connection to a snap that isn’t installed, and a `Failure` for an action that doesn’t exist:

```pycon
>>> snap_testing.Snapd([snap_testing.Snap('prometheus', channel='2/nightly')])
SnapStateValidationError: '2/nightly' is not a valid channel for snap 'prometheus'

>>> snap_testing.Snapd([snap_testing.Snap('prometheus', aliases={'prom': 'prometheus'})])
SnapStateValidationError: alias 'prom' for snap 'prometheus' names app 'prometheus', which is
not in its services []
```

### The store

By default there’s no store, and any snap installs from any channel. If the test passes a list of `StoreSnap` objects as `store=`, only those snaps and channels are available, and an install gets its revision, version and services from the matching `StoreSnap`.

```python
def test_install_starts_prometheus():
    snapd = snap_testing.Snapd(
        store=[
            snap_testing.StoreSnap(
                'prometheus',
                channels={'2/stable': 100},
                version='2.53.0',
                services=['prometheus'],
                daemon_services=['prometheus'],
            ),
        ]
    )
    ctx = ops.testing.Context(PrometheusCharm)

    with snapd:
        ctx.run(ctx.on.install(), ops.testing.State())

    assert snapd.installed == {
        'prometheus': snap_testing.Snap(
            'prometheus',
            channel='2/stable',
            revision=100,
            version='2.53.0',
            services={'prometheus': 'active'},
        ),
    }
```

With a store described, the double raises the same errors snapd would:

| The charm asks for | The library raises |
| --- | --- |
| a snap the store doesn’t have | `NotInStoreError` |
| a channel the snap doesn’t have | `ChannelNotAvailableError` |
| a revision that isn’t on any of the snap’s channels | `RevisionNotAvailableError` |
| a classic snap, without `classic=True` | `NeedsClassicError` |

A refresh to the revision that’s already installed finds nothing to do.

```python
def test_unknown_snap_blocks():
    snapd = snap_testing.Snapd(store=[snap_testing.StoreSnap('grafana')])
    ctx = ops.testing.Context(PrometheusCharm)

    with snapd:
        state_out = ctx.run(ctx.on.install(), ops.testing.State())

    assert state_out.unit_status == ops.BlockedStatus('snap prometheus not found in store')
```

```python
def test_classic_snap():
    snapd = snap_testing.Snapd(store=[snap_testing.StoreSnap('juju', classic=True)])

    with snapd:
        with pytest.raises(snap.NeedsClassicError):
            snap.install('juju')
        snap.install('juju', classic=True)

    assert snapd.installed['juju'].classic
```

### Injected failures

Some failures can’t be described as store contents, so a test can ask for them directly with `Failure`. The `action` is the library function’s name (`'install'`, `'refresh'`, `'set'`, and so on), and `'*'` matches every action. A failure can be limited to one snap and to a number of times. The `error` can be any `charmlibs.snap.Error`, and the charm gets that exact exception object.

snapd not being reachable at all looks like this to a charm:

```python
def test_snapd_unavailable_defers():
    snapd = snap_testing.Snapd(
        failures=[
            snap_testing.Failure('*', error=snap.ConnectionError('Could not connect to snapd'))
        ],
    )
    ctx = ops.testing.Context(PrometheusCharm)

    with snapd:
        state_out = ctx.run(ctx.on.install(), ops.testing.State())

    assert state_out.unit_status == ops.MaintenanceStatus('waiting for snapd')
    assert len(state_out.deferred) == 1
```

With `times=1`, the first attempt fails and the retry works, which is how to test a charm that defers and tries again:

```python
def test_post_refresh_hook_failure_is_retried():
    snapd = snap_testing.Snapd(
        [snap_testing.Snap('prometheus', channel='2/stable', services={'prometheus': 'active'})],
        failures=[
            snap_testing.Failure(
                'refresh',
                snap='prometheus',
                error=snap.ChangeError(
                    'run hook "post-refresh": exit status 1',
                    kind='charmlibs-snap-change-error',
                    value='42',
                    status='Error',
                ),
                times=1,
            ),
        ],
    )
    ctx = ops.testing.Context(PrometheusCharm)
    state = ops.testing.State(config={'channel': '2/edge'})

    with snapd:
        state = ctx.run(ctx.on.config_changed(), state)
        assert len(state.deferred) == 1
        assert snapd.installed['prometheus'].channel == '2/stable'

        state = ctx.run(ctx.on.config_changed(), state)

    assert state.unit_status == ops.ActiveStatus()
    assert snapd.installed['prometheus'].channel == '2/edge'
```

A failure for one snap leaves the others alone:

```python
def test_failure_on_one_snap():
    snapd = snap_testing.Snapd(
        failures=[
            snap_testing.Failure(
                'install',
                snap='grafana',
                error=snap.ChangeError('cannot install', kind='x', value='1', status='Error'),
            ),
        ]
    )

    with snapd:
        snap.install('prometheus')
        with pytest.raises(snap.ChangeError):
            snap.install('grafana')

    assert list(snapd.installed) == ['prometheus']
```

### Checking what the charm did

`installed` only shows where the charm ended up. When the order matters (stopping a service before refreshing it, for example), `history` has every operation the charm performed:

```python
def test_refresh_stops_service_first():
    snapd = snap_testing.Snapd([
        snap_testing.Snap('prometheus', channel='2/stable', services={'prometheus': 'active'}),
    ])
    ctx = ops.testing.Context(PrometheusCharm)

    with snapd:
        ctx.run(ctx.on.config_changed(), ops.testing.State(config={'channel': '2/edge'}))

    assert snapd.history == [
        snap_testing.Stop('prometheus', services=('prometheus',), disable=False),
        snap_testing.Refresh('prometheus', channel='2/edge', revision=None),
        snap_testing.Start('prometheus', services=('prometheus',), enable=False),
    ]
```

Reads are recorded too, so a charm that only writes configuration when it has changed can be checked for that:

```python
    assert snapd.history == [
        snap_testing.ConfigGet('grafana', keys=('http.port',)),
        snap_testing.ConfigSet('grafana', values={'http.port': 8080}),
    ]
```

There’s one operation type for each library function that reads or changes snap state, and each takes the snap name first:

```python
Install(snap, channel, revision, classic)
Refresh(snap, channel, revision)
Remove(snap, purge)
Hold(snap, until)  # None for an indefinite hold.
Unhold(snap)
Start(snap, services, enable)
Stop(snap, services, disable)
Restart(snap, services)
ConfigGet(snap, keys)
ConfigSet(snap, values)
ConfigUnset(snap, keys)
Connect(snap, plug, slot)
Disconnect(snap, plug, slot)
Alias(snap, app, alias)
Unalias(snap, alias)
Logs(snap, limit)
```

`list_one` isn’t recorded. `ensure_installed` calls it every time, so it would show up in every assertion without saying anything. Only operations that worked are recorded, and an operation that didn’t need to do anything (installing a snap that’s already there, for example) isn’t recorded either. A failure the test injected shows up in what the charm did next, not in `history`.

A reconcile-style charm will probably only check `installed`, and a charm that has to do things in a particular order will mostly check `history`. Either is fine, and so is both.

### `mocked`

Under OP093, every testing package has a `mocked()`: a reentrant context manager that takes no arguments and mocks out the library’s internals. snap isn’t an interface library, so `snap_testing` has no `provider` or `requirer`, only `mocked()`.

`snap_testing.mocked()` is a small wrapper around `Snapd`. If a `Snapd` is already open, `mocked()` joins it, so the code under test talks to the test’s `Snapd`. If not, it opens a new empty one, with no store described, for as long as its own `with` lasts:

```python
def test_mocked_alone_is_per_dispatch():
    with snap_testing.mocked() as a:
        snap.ensure_installed('prometheus', '2/stable')
        with snap_testing.mocked() as b:
            assert b is a
    with snap_testing.mocked() as c:
        assert c.installed == {}  # A new, empty Snapd.
```

OP089’s `Juju` opens each testing package’s `mocked()` around every dispatch. A test that wants snap state to carry from one dispatch to the next, or wants to check it afterwards, opens a `Snapd` around the whole test (the fixture is the easiest way), and `Juju`’s `mocked()` calls join it:

```python
def test_prometheus_installs_on_deploy(snapd):
    juju = ops.testing.Juju()
    juju.deploy('./charms/prometheus')
    juju.settle()

    assert snapd.installed['prometheus'].channel == '2/stable'
```

Without an outer `Snapd`, every dispatch starts from an empty machine, so a snap installed in `install` has gone by the next hook. That’s fine for a charm whose use of snaps isn’t what the test is about.

That does mean the result depends on whether the scope is opened once per test or once per dispatch, which is the question OP093 has open about scope-insensitivity. This spec doesn’t try to settle it. Keeping the state in the scope seems the most sensible choice for now, with an outer `Snapd` being how a test chooses how long that state lives. If OP093 decides `mocked()` has to be scope-insensitive, the bare `mocked()` would need to keep its state somewhere else (keyed by the unit, probably), and `Snapd` wouldn’t change.

`mocked()` has no arguments because a test that cares about the starting state, the store, or failures also wants something to check afterwards, and that’s what a `Snapd` is for.

### Without `ops.testing`

Nothing in the double uses ops, so it works the same with `Harness`:

```python
def test_harness():
    snapd = snap_testing.Snapd()
    harness = ops.testing.Harness(GrafanaCharm)

    with snapd:
        snap.install('grafana')
        harness.begin()
        harness.update_config({'port': 9000})

    assert snapd.installed['grafana'].config == {'http.port': 9000}
```

and with plain functions that a charm has moved out of its event handlers, like the `workload.reconcile` example in [Setting up the machine](#setting-up-the-machine).

### Behaviour the double reproduces

Because the real library runs on top of the double, the edge cases behave as they do on a real machine. These are the ones a hand-written stub most often gets wrong, and each has a test, either in the double’s own suite or in `snap`’s converted unit tests (see [Avoiding drift](#avoiding-drift)).

* `install` of a snap that’s already installed returns a falsy value instead of raising, as do `remove` of a snap that isn’t installed and (with a store described) `refresh` when there’s nothing newer.
* `connect` of a plug and slot that are already connected does nothing. `disconnect` of a plug and slot that aren’t connected raises `APIError`, but a `disconnect` that names only one side and matches nothing doesn’t raise.
* `hold`, `refresh`, `start`, `get` and the other per-snap functions raise `NotInstalledError` for a snap that isn’t installed. snapd’s answers to most of these are ambiguous, so the library makes extra requests to work out which error it is, and the double answers those the same way snapd does.
* `get_one` for a key the snap doesn’t have raises `OptionNotFoundError`.
* `start`, `stop` or `restart` for a service the snap doesn’t have (or for a snap with no services) raises `AppNotFoundError`.
* `alias` for an app the snap doesn’t have, or for an alias another snap already has, raises `ChangeError` when the asynchronous change fails, as it does with snapd, not when the request is made.
* `system` and `core` share one configuration, whether or not a `core` snap is installed, and removing `core` drops what was set on it.

```python
def test_already_installed_is_falsy():
    with snap_testing.Snapd([snap_testing.Snap('prometheus')]):
        assert not snap.install('prometheus')


def test_not_installed():
    with snap_testing.Snapd():
        with pytest.raises(snap.NotInstalledError):
            snap.hold('prometheus')


def test_alias_unknown_app():
    with snap_testing.Snapd([snap_testing.Snap('prometheus')]):
        with pytest.raises(snap.ChangeError):
            snap.alias('prometheus', 'promtool', 'promtool')
```

### Scope for a first release

`ensure_installed`, `install`, `refresh`, `remove`, `list_one`, `hold`, `unhold`, `start`, `stop`, `restart`, `get`, `get_one`, `set`, `unset`, `connect`, `disconnect`, `alias`, and `unalias` are all modelled. `logs` returns the entries the test gave each `Snap`, without applying `limit`. A charm that reads snap logs is usually passing them on somewhere, so the test will want to control exactly what it gets.

A request to an endpoint the double doesn’t model raises `NotImplementedError` naming the endpoint. If a charm uses something the double doesn’t cover, its test should fail and say why, not pass when it shouldn’t:

```text
NotImplementedError: charmlibs-snap-testing does not model GET '/v2/snapshots'
```

Two snapd behaviours are left out deliberately. Both depend on the machine, so there’s no value the double could return that would be right.

Real snapd rejects an unknown system option (`snap.set('system', {'totally.bogus.key': 'x'})`) with a failed change. Doing the same would mean carrying a copy of snapd’s option schema, which is large, changes between snapd releases, and isn’t something charm tests check. The double accepts any key.

On real snapd, `snap.get('system')` with no keys always includes values snapd works out from the machine, such as the hostname and timezone. Any value the double invented would differ from every real machine anyway, and a charm test that passed because of an invented hostname wouldn’t be testing much. The double returns only what’s been set.

The library’s own socket handling (retrying the connection, the request timeout, and polling asynchronous changes) is also out of scope. That’s the library’s responsibility, not the charm’s, and the library’s functional tests cover it.

### Avoiding drift

The risk with any test double is that it drifts away from the real thing, and charm tests keep passing against behaviour real snapd doesn’t have. There are two things in place to catch that.

First, `snap`’s own unit tests run through the double. Every test in `snap/tests/unit/` that checks an outcome was moved from a mocked client with canned responses to a `Snapd`, so each change to `charmlibs.snap` is tested against the double in the same CI run, and a library change the double doesn’t keep up with fails there rather than in some charm’s tests. By file:

* `test_not_found.py`: all converted. An empty `Snapd` gives “not found” for every public function, through the same extra requests a charm test goes through.
* `test_snapd_snaps.py`, `test_snapd_apps.py`, `test_snapd_conf.py`, and `test_snapd_logs.py`: every outcome test converted.
* `test_snapd_interfaces.py`: the tests for the extra requests and for errors converted. The rest check the shape of the request.
* `test_client.py`, `test_utils.py`, `test_functions.py`, `test_empty_or_blank.py`, `test_errors.py`, and `test_snapd_aliases.py`: unchanged.

The unchanged tests check the exact request the library sends, or argument validation that fails before any request is made. The double can say what’s installed and what was raised, but not what a request body looked like, so those tests keep their mocks. Converting the others turned up two places where the double and the library disagreed, and both are fixed.

Second, the functional suite is the reference. `snap/tests/functional/` runs against real snapd, and if the double and a functional test disagree, the double is wrong. What that found for the implementation is under [Further Information](#further-information).

### Relationship to `ops.testing`

The double works with `ops.testing` but doesn’t depend on it or plug into it.

`ops.testing.State` models what Juju owns. Snaps are machine state that Juju knows nothing about, so `State(snaps=...)` doesn’t belong there (and if it did, so would apt packages and systemd units). `Context` has no way for a library to add its own state or mocks to a run, so with `Context` the double wraps `Context.run()` instead of living inside it. That also means the same object works under `Harness` and in plain pytest.

OP089’s `Juju` does have a hook for this, OP093’s `mocked()`, and `snap_testing.mocked()` uses it (see [`mocked`](#mocked)).

The fixture already wraps the whole test, which covers anything wrapping `Context.run()` would. The gap is a test that calls `Context.run()` several times with the same `Snapd`, where `history` keeps growing across the runs. If that turns out to be a problem, it can be solved in `charmlibs-snap-testing` without any change to ops, for example by letting a test mark a point in `history` and ask for what came after it.

## Further Information

### Implementation

The double is built as a new `charmlibs-snap-testing` distribution on the [`feat/snap-testing-double-squashed`](https://github.com/tonyandrewmeyer/charmlibs/tree/feat/snap-testing-double-squashed/snap/testing) branch of a `charmlibs` fork, as two commits: the package, then `snap`’s unit tests moved onto it. There’s no `charmlibs` PR yet.

On that branch, `snap`’s unit tests pass through the double (857 passed, 14 skipped), as does the double’s own suite (147). Every example in this spec is also run against the branch.

`snap`’s full functional suite was run against snapd 2.76 in a VM (501 passed). Then each place where the double and snapd might disagree was checked by sending the same requests to the snapd socket directly. Of five suspects, four were bugs in the double, all now fixed:

* With a store described, a refresh with no channel used `latest/stable` instead of the channel the snap was tracking.
* A service action on a snap that isn’t installed raised the wrong error kind and message.
* `connect` accepted an empty plug snap or plug name.
* `system` and `core` configuration went out of sync when a `core` snap was in the starting state, and survived `core` being removed. (Checking the second half needed a throwaway container, since `core` can’t be removed from under a running snapd.)

The fifth was the double being right. The two behaviours left out in [Scope for a first release](#scope-for-a-first-release) were found in the same check.

The public functions turn the first three bugs into `NotInstalledError`, so a charm wouldn’t have seen them. The double’s own tests for them check the raw endpoint responses, which is what the socket check compared.

### Alternatives

Monkeypatching the public functions in each charm’s tests is what charms do now, and [Rationale](#rationale) covers why it isn’t enough.

A submodule, `charmlibs.snap.testing`, was also considered. That would avoid one distribution reaching into another’s private module, but it would ship a fake snapd inside every charm that uses `charmlibs.snap`, and it wouldn’t get the CI check that keeps a `-testing` distribution at the same version as its library. The private module belongs to the same repository and the same people as the double, and with the versions locked together the two can’t drift apart without CI noticing.

### Related specs

* OP077 (charm library testing) sets out the layout, the `[testing]` extra, and the version lock that `charmlibs-snap-testing` follows.
* OP093 (charmlibs testing packages API) defines the testing package API, including the `mocked()` that `snap_testing` provides, and has the open question about mocking scope mentioned in [`mocked`](#mocked).
* OP089 (multiple-charm state transition tests) defines `Juju`, which opens each testing package’s `mocked()` around every dispatch.

### Future work

* A way to add doubles to `Context`, like the one `mocked()` gives `Juju` (perhaps `Context(charm, extensions=[snapd])`), would save single-charm tests from opening them by hand. That’s a separate conversation, and the double doesn’t need it. Anything like that would most likely use the context manager protocol `Snapd` already has, so adopting it later wouldn’t change the double’s API.
* `apt`, `systemd`, `sysctl`, and `passwd` can’t be faked the same way: each runs a command with `subprocess` instead of going through a client module, and `sysctl` and `passwd` also read and write files. So the double is snap-only for now. The parts that could be shared (the operation history, injected failures, and opening several doubles at once) are small enough to move into a shared package later without changing this one, and fixtures already make it easy to use several doubles together: `def test_x(snapd, apt):`.
