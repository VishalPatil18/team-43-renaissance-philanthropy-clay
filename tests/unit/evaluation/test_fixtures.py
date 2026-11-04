from tests.fixtures.traces import NAMES, load


def test_every_fixture_parses_and_ends_with_run_end():
    for name in NAMES:
        trace, manifest, reference = load(name)
        assert trace.events[-1].type == "run_end"
        assert not trace.incomplete
        assert manifest.task_reference_version == reference.version
