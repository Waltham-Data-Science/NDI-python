"""Tests for ndi.fun.probe.channelCount.

MATLAB counterpart: +ndi/+fun/+probe/channelCount.m

The count decides how wide a placeholder channel map is written, so it is
only useful if "I could not tell" is distinguishable from a number. These
check that every unanswerable case comes back None rather than 0 or 1 --
a map of the wrong width is accepted by a sorter, a missing map is not.
"""

from __future__ import annotations

from ndi.fun.probe import channelCount


class FakeProbe:
    """A probe whose getchanneldevinfo returns MATLAB's shape.

    ``ndi.probe.timeseries_mfdaq`` returns
    ``(device, device_epoch, channeltype, channellist)`` -- the channel list
    last, as it is in MATLAB's five outputs.
    """

    def __init__(self, channels=4, epochs=("e1", "e2")):
        self._channels = channels
        self._epochs = [{"epoch_id": e} for e in epochs]
        self.asked = []

    def epochtable(self):
        return self._epochs, "hash"

    def getchanneldevinfo(self, epoch):
        self.asked.append(epoch)
        return (None, None, "ai", list(range(1, self._channels + 1)))


def test_the_channel_list_is_counted():
    assert channelCount(FakeProbe(channels=6)) == 6


def test_the_first_epoch_is_used_by_default():
    probe = FakeProbe()
    channelCount(probe)
    assert probe.asked == ["e1"]


def test_a_named_epoch_is_used_when_given():
    probe = FakeProbe()
    channelCount(probe, "e2")
    assert probe.asked == ["e2"]


def test_a_dict_answer_is_read_too():
    """The base ndi.probe returns a dict rather than MATLAB's tuple."""

    class DictProbe(FakeProbe):
        def getchanneldevinfo(self, epoch):  # noqa: ARG002
            return {"channels": [1, 2, 3]}

    assert channelCount(DictProbe()) == 3


def test_a_probe_with_no_epochs_cannot_answer():
    assert channelCount(FakeProbe(epochs=())) is None


def test_a_probe_that_raises_cannot_answer():
    class Broken(FakeProbe):
        def getchanneldevinfo(self, epoch):
            raise RuntimeError("no epochprobemap")

    assert channelCount(Broken()) is None


def test_a_probe_with_no_getchanneldevinfo_cannot_answer():
    class Bare:
        def epochtable(self):
            return [{"epoch_id": "e1"}], "hash"

    assert channelCount(Bare()) is None


def test_an_answer_with_no_channel_list_in_it_cannot_answer():
    class Empty(FakeProbe):
        def getchanneldevinfo(self, epoch):  # noqa: ARG002
            return {"daqsystem": None}

    assert channelCount(Empty()) is None


def test_an_epoch_id_a_probe_will_not_take_falls_back_to_its_number():
    """The base Python probe wants an epoch NUMBER and raises on a string;
    MATLAB asks by epoch_id. Both name the same epoch."""

    class NumbersOnly(FakeProbe):
        def getchanneldevinfo(self, epoch):
            self.asked.append(epoch)
            if not isinstance(epoch, int):
                raise TypeError("epoch must be a number")
            return (None, None, "ai", [1, 2])

    probe = NumbersOnly()
    assert channelCount(probe) == 2
    assert probe.asked == ["e1", 1]
