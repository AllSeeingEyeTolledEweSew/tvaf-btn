# The author disclaims copyright to this source code. Please see the
# accompanying UNLICENSE file.

import contextlib


class SourceDelta(object):

    def __init__(self, from_sequence, to_sequence):
        assert from_sequence < to_sequence, (from_sequence, to_sequence)
        self.from_sequence = from_sequence
        self.to_sequence = to_sequence


class CheckpointError(Exception):

    pass


@contextlib.contextmanager
def checkpoint(state, config, delta):
    if bool(delta.from_sequence):
        config_in_db = state.get_config()
        if config != config_in_db:
            raise CheckpointError(
                "%s != %s" % (config, config_in_db))
        sequence_in_db = state.get_sequence()
        if delta.from_sequence != sequence_in_db:
            raise CheckpointError(
                "%s != %s" % (delta.from_sequence, sequence_in_db))
    yield
    state.set_config(config)
    state.set_sequence(delta.to_sequence)
