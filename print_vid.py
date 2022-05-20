import xml.etree.ElementTree as ET
from pathlib import Path
import datetime
import pysrt
import copy
import re


def copy_new_children(el, children):
    new_el = ET.Element(el.tag)
    for key, value in el.attrib.items():
        new_el.set(key, value)
    for child in children:
        new_el.append(child)
    return new_el


def divide_pair(match):
    pair = [*'00']
    if match:
        pair[0] = match.group(1) or "0"
        pair[1] = match.group(2) or "0"
    try:
        pair[0] = int(pair[0])
        pair[1] = int(pair[1])
    except ValueError:
        return 0
    try:
        return pair[0] / pair[1]
    except ZeroDivisionError:
        return float(pair[0])


def parse_ratio(el, key):
    s = el.attrib[key]
    ratio_regex = '(\\d+)(?:/(\\d+))?s$'
    match = re.search(ratio_regex, s)
    return divide_pair(match)


def write_ratio(ratio, fps):
    numerator = round(ratio * fps)
    return f"{numerator}/{fps}s"


def to_last(items, el_i):
    return el_i + 1 == len(items)


def to_sample(limiter, el_i):
    # Exhaust generator until index
    for _ in range(el_i):
        next(limiter)
    # +/- one partial limit
    limit_pre = next(limiter)[1]
    limit_self = next(limiter)
    limit_post = next(limiter)[0]
    before = (limit_pre + limit_self[0]) / 2
    after = (limit_self[1] + limit_post) / 2
    # Invalid limits
    if limit_pre < 0:
        before = -1
    if limit_post < 0:
        after = -1
    return [before, after]


class AuthoredClip:

    def __init__(self, author, clip, captions):
        self.children = captions
        self._a = author
        self._c = clip

    def __repr__(self):
        line0 = ''
        limit = self.limit
        name = self._a['name']
        t0 = datetime.timedelta(seconds=limit[0])
        t1 = datetime.timedelta(seconds=limit[1])
        if len(self.children) and len(self.captions):
            line0 = self.captions[0].attrib['name']
            line0 += '\n'
        out = f'{t0} --> {t1}: {name}\n{line0}'
        for child in self.children:
            sym = child._c.attrib.get('TODO', ' ')
            out = out + f' {sym}  {child}\n'
        return out

    @property
    def author(self):
        return self._a

    @property
    def captions(self):
        caps = list(self._c.iter('caption'))
        return caps if len(caps) else []

    @property
    def ref(self):
        return self._c.attrib['ref']

    @property
    def start(self):
        return parse_ratio(self._c, 'start')

    @property
    def limit(self):
        o = parse_ratio(self._c, 'offset')
        d = parse_ratio(self._c, 'duration')
        return [o, o + d]

    def update_clip(self, new_assets):
        old_file = self._c.attrib['name']
        name = self._a['name']
        for asset in new_assets:
            new_file = asset['path']
            if asset['name'] != name:
                continue
            if asset['old'] != old_file:
                continue
            ref = asset['ref']
            self._c.set('ref', ref)
            self._c.set('name', new_file)
            return True
        return False

    def split_output_time(self, lines):
        [t0, t1] = self.limit
        # Compute noise gap ratio
        total_t = t1 - t0
        caption_t = 0
        for line in lines:
            d = parse_ratio(line.caption, 'duration')
            caption_t += d
        gap_scale = total_t / caption_t
        # Yield initial output time
        yield [-1, t0]
        current = t0
        # Yield interediate output times
        for line in lines:
            d = parse_ratio(line.caption, 'duration')
            # Update output timeframe
            current_start = current
            current += d * gap_scale
            # Yield partitition for clip
            yield [current_start, current]
        # Yield final output time
        yield [t1, -1]

    @property
    def input_limit(self):
        before = self.start
        after = before
        # Sum durations of all captions
        for caption in self.captions:
            d = parse_ratio(caption, 'duration')
            after += d
        return [before, after]

    def to_output_sample(self, el_i, lines):
        limiter = self.split_output_time(lines)
        return to_sample(limiter, el_i)

    def set_precise_limit(self, new_limit, line, fps):
        t0 = new_limit[0]
        t1 = line.input_end if line.input_end > 0 else new_limit[1]
        self._c.set('offset', write_ratio(t0, fps))
        self._c.set('duration', write_ratio(t1 - t0, fps))

    def join_timeline(self, spine):
        clip = copy.deepcopy(self._c)
        spine.append(clip)


def find_author(authors, text):
    for author in authors:
        regex = author['re']
        match = re.match(regex, text, re.I)
        if match:
            return author
    return None


def to_project(root):
    library = next(root.iter('library'))
    event = next(library.iter('event'))
    return next(event.iter('project'))


def to_sequence(proj):
    return next(proj.iter('sequence'))


class TextChecker:

    def __init__(self, clip):
        self._c = clip

    def fit_duration(self, el):
        o = parse_ratio(el, 'offset')
        d = parse_ratio(el, 'duration')
        # Compare total time to/after clip
        max_time = parse_ratio(self._c, 'duration')
        basis = parse_ratio(self._c, 'start')
        before = o - basis
        after = before + d
        # Allow if within maximum
        if after >= max_time:
            return max_time - before
        return d


class LineSnip:

    def __init__(self, caption, found, is_first, input_end):
        self.caption = caption
        self.found = found
        self.is_first = is_first
        self.input_end = input_end


class ClipSnip:

    def __init__(self, clip, lines):
        self.lines = lines
        self.clip = clip

    def shrink(self, line):
        clip = copy.deepcopy(self.clip)
        return ClipSnip(clip, [line])


def to_lines(captions, clip, authors, clip_input_end):
    lines = []
    for cap_i, caption in enumerate(captions):
        text = caption.attrib['name']
        is_first = cap_i == 0
        found = find_author(authors, text)
        input_end = clip_input_end if to_last(captions, cap_i) else -1
        line_args = (caption, found, is_first, input_end)
        lines.append(LineSnip(*line_args))
    return lines


def to_snips(gap_iter, old_clips, authors, fps):
    carried = {}
    new_clips = []
    for clip in old_clips:
        new_caps = []
        # Apply carried clips
        ref = clip.attrib['ref']
        for cap in carried.get(ref, []):
            cap.set('TODO', 'x')
            new_caps.append(cap)
        carried[ref] = []
        clip_offset = parse_ratio(clip, 'offset')
        clip_time = parse_ratio(clip, 'duration')
        total_time = clip_offset + clip_time
        for cap in clip.iter('caption'):
            sub_gap = next(gap_iter)
            # Add subtitle gap to delta
            full_sub_time = sub_gap.delta
            excess = max(sub_gap.end - total_time, 0)
            remains = full_sub_time - excess
            # Create new captions
            new_cap_0 = copy.deepcopy(cap)
            new_cap_1 = copy.deepcopy(cap)
            if remains > 0.1 * full_sub_time:
                new_offset = sub_gap.start
                new_cap_1.set('offset', write_ratio(new_offset, fps))
                new_cap_0.set('duration', write_ratio(remains, fps))
                new_caps.append(new_cap_0)
            if excess > 0.1 * full_sub_time:
                # Split the caption
                new_offset = sub_gap.start + remains
                new_cap_1.set('offset', write_ratio(new_offset, fps))
                new_cap_1.set('duration', write_ratio(excess, fps))
                # Add clips to carry over
                caps = carried.get(ref, [])
                carried[ref] = caps + [new_cap_1]

        # Update clips
        new_clip = copy_new_children(clip, new_caps)
        new_clips.append(new_clip)

    last_caption = None
    for clip_i, clip in enumerate(new_clips):
        # End of clip input
        clip_input_end = -1
        if not to_last(new_clips, clip_i):
            next_clip = new_clips[clip_i + 1]
            next_ref = next_clip.attrib['ref']
            if next_ref == clip.attrib['ref']:
                clip_input_end = parse_ratio(next_clip, 'offset')
        # Yield info for clip
        captions = list(clip.iter('caption'))
        # Handle cases without captions
        if not len(captions):
            if last_caption != None:
                fake_caption = copy.deepcopy(last_caption)
                fake_caption.set('duration', clip.attrib['duration'])
                fake_caption.set('offset', clip.attrib['start'])
                t_style = fake_caption.find("text").find("text-style")
                t_style_def = fake_caption.find("text-style-def")
                fake_ref = "placeholder-" + t_style.attrib["ref"]
                t_style_def.set("id", fake_ref)
                t_style.set("ref", fake_ref)
                captions = [ fake_caption ]
        else:
            last_caption = copy.deepcopy(captions[-1])
        lines = to_lines(captions, clip, authors, clip_input_end)
        yield ClipSnip(clip, lines)


def make_solo_clip(snip, line, author, fps):
    snip_clip = snip.shrink(line).clip
    # Replace old captions with solo caption
    new_caption = copy.deepcopy(line.caption)
    new_clip = copy_new_children(snip_clip, [new_caption])
    new_start = parse_ratio(new_caption, 'offset')
    # First clip starts at the start
    start = parse_ratio(new_clip, 'start')
    new_start = start if line.is_first else new_start
    new_clip.set('start', write_ratio(new_start, fps))
    if 'TODO' in new_caption.attrib:
        new_clip.set('TODO', 'x')
    return AuthoredClip(author, new_clip, [])


def print_vid(gap_iter, spine, authors, fps):
    a_map = {a['name']: a for a in authors}
    names = [a['name'] for a in authors]
    no_weights = {n: 0 for n in names}
    author = authors[-1]
    authored_clips = []

    # Create clip list in output order
    all_clips = list(spine.iter('asset-clip'))
    for snip in to_snips(gap_iter, all_clips, authors, fps):
        # List all captions
        captions = []
        weights = copy.deepcopy(no_weights)
        # First, capture caption durations
        for el_i, line in enumerate(snip.lines):
            if line.found:
                author = line.found
            k = author['name']
            weights[k] += parse_ratio(line.caption, 'duration')
            a_caption = make_solo_clip(snip, line, author, fps)
            new_limit = a_caption.to_output_sample(el_i, snip.lines)
            a_caption.set_precise_limit(new_limit, line, fps)
            captions.append(a_caption)
        # Find most common author
        most_author = a_map[max(weights, key=weights.get)]
        # Yield most popular author and clip
        a_clip = AuthoredClip(most_author, snip.clip, captions)
        authored_clips.append(a_clip)

    return authored_clips


def read_spines(all_subs, authors, opts):
    fps = opts['fps']
    new_seq = opts['seq']
    gap_iter = subs_to_gaps(all_subs)
    for spine in list(new_seq.iter('spine')):
        yield print_vid(gap_iter, spine, authors, fps)


def sub_to_delta(sub, key):
    t0 = datetime.date.min
    d0 = datetime.datetime.min
    t1 = getattr(sub, key).to_time()
    d1 = datetime.datetime.combine(t0, t1)
    return (d1 - d0).total_seconds()


class SubGap:

    def __init__(self, start0, start1):
        self.delta = start1 - start0
        self.start = start0
        self.end = start1


def subs_to_gaps(all_subs):
    list0 = all_subs
    list1 = all_subs[1:] + [None]
    lists = zip(list0, list1)
    for s0, s1 in lists:
        start0 = sub_to_delta(s0, 'start')
        end0 = sub_to_delta(s0, 'end')
        if not s1:
            yield SubGap(start0, end0)
            break
        start1 = sub_to_delta(s1, 'start')
        yield SubGap(start0, start1)


def main(all_subs, audio_tree, authors):
    # Open audio project
    audio_root = audio_tree.getroot()
    audio_proj = to_project(audio_root)
    seq_audio = to_sequence(audio_proj)
    # Audio spine with precise cuts
    opts_audio = {
        'seq': seq_audio,
        'fps': 30
    }
    spines = read_spines(all_subs, authors, opts_audio)
    for a_clips in spines:
        for clip_i, a_clip in enumerate(a_clips):
            print(clip_i + 1)
            print(a_clip)


if __name__ == "__main__":
    fname = 'dev_tools_game_0'
    in_srt = Path(f'./{fname}.srt')
    in_xml = Path(f'./{fname}.fcpxml')
    all_subs = pysrt.open(in_srt)
    audio_tree = ET.parse(in_xml)
    any_word = '\\w{1,15}'
    authors = [{
        'name': 'Adam',
        're': '^Adam: '
    }, {
        'name': 'TVQuizPhd',
        're': '^TVQuizPhd: '
    }, {
        'name': 'Noise',
        're': '^Noise: '
    }, {
        'name': 'Cat',
        're': '^Cat: '
    }, {
        'name': 'Other',
        're': f'^{any_word}: '
    }]
    main(all_subs, audio_tree, authors)
