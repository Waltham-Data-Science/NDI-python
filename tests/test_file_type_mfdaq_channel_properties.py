"""ndi.file.type.mfdaq_epoch_channel.create_properties against MATLAB.

MATLAB's create_properties DERIVES three fields the caller does not supply --
number from the channel name, group from that number, and dataclass from the
type -- and returns the channels sorted by type and then by number. The port
copied its input through unchanged, so every channel came out with number 0,
group 0 and an empty dataclass, and channelgroupdecoding (which reads group)
put everything in one group.
"""

from __future__ import annotations

import pytest

from ndi.file.type.mfdaq_epoch_channel import (
    CHANNELS_PER_GROUP,
    TYPE_DATACLASS,
    ChannelInfo,
    ndi_file_type_mfdaq__epoch__channel,
)


def build(channels, **kwargs):
    return ndi_file_type_mfdaq__epoch__channel().create_properties(channels, **kwargs)


def ch(name, type_, **kw):
    return dict(name=name, type=type_, **kw)


class TestNumberIsDerivedFromTheName:
    def test_the_numeric_suffix_becomes_the_number(self):
        m = build([ch("ai7", "analog_in")])
        assert m.channel_information[0].number == 7

    def test_it_used_to_be_zero(self):
        # from_dict's default; nothing computed it.
        assert ChannelInfo.from_dict({"name": "ai7", "type": "analog_in"}).number == 0

    def test_a_multi_digit_suffix(self):
        assert build([ch("ai128", "analog_in")]).channel_information[0].number == 128

    def test_a_name_with_no_digits_is_rejected(self):
        with pytest.raises(ValueError):
            build([ch("analog", "analog_in")])


class TestGrouping:
    """MATLAB: group = 1 + floor(number / channels_per_group)."""

    def test_a_low_channel_is_in_group_one(self):
        assert build([ch("ai1", "analog_in")]).channel_information[0].group == 1

    def test_the_boundary_is_the_per_type_size(self):
        size = CHANNELS_PER_GROUP["analog_in"]
        below = build([ch(f"ai{size - 1}", "analog_in")]).channel_information[0]
        at = build([ch(f"ai{size}", "analog_in")]).channel_information[0]
        assert below.group == 1
        assert at.group == 2

    def test_digital_channels_use_the_larger_group_size(self):
        assert CHANNELS_PER_GROUP["digital_in"] == 512
        assert build([ch("di500", "digital_in")]).channel_information[0].group == 1

    def test_a_caller_can_override_the_group_size(self):
        m = build([ch("ai5", "analog_in")], analog_in_channels_per_group=2)
        assert m.channel_information[0].group == 3  # 1 + 5//2

    def test_an_unknown_type_still_gets_a_group(self):
        assert build([ch("zz1", "something_else")]).channel_information[0].group == 1


class TestDataclass:
    def test_analog_channels_are_ephys(self):
        assert build([ch("ai1", "analog_in")]).channel_information[0].dataclass == "ephys"

    def test_digital_channels_are_digital(self):
        assert build([ch("di1", "digital_in")]).channel_information[0].dataclass == "digital"

    def test_time_channels_are_time(self):
        assert build([ch("t1", "time")]).channel_information[0].dataclass == "time"

    def test_a_caller_can_override_a_dataclass(self):
        m = build([ch("ai1", "analog_in")], analog_in_dataclass="custom")
        assert m.channel_information[0].dataclass == "custom"

    def test_every_matlab_type_has_a_dataclass(self):
        assert set(TYPE_DATACLASS) == set(CHANNELS_PER_GROUP)


class TestEventMarkerTextAreOneType:
    """MATLAB folds event, marker and text into one synthetic type."""

    def test_all_three_get_the_eventmarktext_dataclass(self):
        m = build([ch("e1", "event"), ch("mk2", "marker"), ch("tx3", "text")])
        assert {c.dataclass for c in m.channel_information} == {"eventmarktext"}

    def test_their_own_type_is_preserved(self):
        m = build([ch("e1", "event"), ch("mk2", "marker")])
        assert {c.type for c in m.channel_information} == {"event", "marker"}

    def test_they_share_one_group_counter(self):
        # All three land in group 1 because they are counted together against
        # the eventmarktext group size, not against three separate ones.
        m = build([ch("e1", "event"), ch("mk2", "marker"), ch("tx3", "text")])
        assert {c.group for c in m.channel_information} == {1}


class TestOrdering:
    def test_channels_are_sorted_by_number_within_a_type(self):
        m = build([ch("ai10", "analog_in"), ch("ai2", "analog_in"), ch("ai1", "analog_in")])
        assert [c.number for c in m.channel_information] == [1, 2, 10]

    def test_types_are_grouped_together(self):
        m = build(
            [
                ch("ai2", "analog_in"),
                ch("di1", "digital_in"),
                ch("ai1", "analog_in"),
                ch("di2", "digital_in"),
            ]
        )
        types = [c.type for c in m.channel_information]
        assert types == sorted(types)

    def test_eventmarktext_comes_last(self):
        m = build([ch("e1", "event"), ch("ai1", "analog_in")])
        assert [c.type for c in m.channel_information] == ["analog_in", "event"]


class TestSuppliedFieldsSurvive:
    def test_name_type_rate_offset_and_scale_are_carried_through(self):
        m = build(
            [ch("ai1", "analog_in", sample_rate=30000.0, offset=1.5, scale=0.25, time_channel=2)]
        )
        c = m.channel_information[0]
        assert c.name == "ai1"
        assert c.type == "analog_in"
        assert c.sample_rate == 30000.0
        assert c.offset == 1.5
        assert c.scale == 0.25
        assert c.time_channel == 2

    def test_channelinfo_objects_are_accepted_as_well_as_dicts(self):
        m = build([ChannelInfo(name="ai4", type="analog_in")])
        assert m.channel_information[0].number == 4


class TestGroupDecodingNowSeesRealGroups:
    def test_channels_in_different_groups_decode_into_different_groups(self):
        size = CHANNELS_PER_GROUP["analog_in"]
        m = build([ch("ai1", "analog_in"), ch(f"ai{size}", "analog_in")])
        groups, in_groups, in_output = m.channelgroupdecoding(
            m.channel_information, "analog_in", [1, size]
        )
        assert groups == [1, 2]
        assert in_output == [[0], [1]]
        assert in_groups == [[0], [0]]

    def test_channels_in_one_group_decode_together(self):
        m = build([ch("ai1", "analog_in"), ch("ai2", "analog_in")])
        groups, in_groups, in_output = m.channelgroupdecoding(
            m.channel_information, "analog_in", [1, 2]
        )
        assert groups == [1]
        assert in_groups == [[0, 1]]
        assert in_output == [[0, 1]]

    def test_an_unknown_channel_raises(self):
        m = build([ch("ai1", "analog_in")])
        with pytest.raises(ValueError, match="not found in record"):
            m.channelgroupdecoding(m.channel_information, "analog_in", [99])
