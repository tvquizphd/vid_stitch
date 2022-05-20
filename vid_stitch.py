from print_vid import read_spines
from print_vid import to_project, to_sequence
from urllib.parse import quote, unquote, urlparse
import xml.etree.ElementTree as ET
import opentimelineio as otio
from pathlib import Path
from uuid import uuid4
import pysrt
import re


def extract_file_base(text):
    return Path(unquote(urlparse(text).path)).parent


def update_resources(root, new_assets):
    max_id = 0
    audio_rate = 48000
    base_path = Path('/')
    resources = next(root.iter('resources'))
    fmt = next(resources.iter('format')).attrib['id']

    for asset in resources.iter('asset'):
        audio_rate = asset.attrib['audioRate']
        base_path = extract_file_base(asset.attrib['src'])
        match = re.search('(\\d+)$', asset.attrib['id'])
        max_id = max(max_id, int(match.group(0)))

    for new_asset in new_assets:
        max_id = max_id + 1
        asset_id = f'r{max_id}'
        asset_path = new_asset['path']
        ext = Path(asset_path).suffix
        src = base_path / asset_path
        uida = str(uuid4())
        uidb = str(uuid4())
        # Generate a new asset
        asset = ET.SubElement(resources, 'asset')
        new_asset['ref'] = asset_id
        asset.set('id', asset_id)
        asset.set('name', uida)
        asset.set('uid', uidb + ext)
        asset.set('src', quote(f'file://{src}'))
        asset.set('audioRate', str(audio_rate))
        asset.set('hasAudio', '1')
        asset.set('hasVideo', '1')
        asset.set('format', fmt)

    return new_assets


def write_spines(all_subs, authors, new_assets, opts):
    tree = opts['tree']
    proj = opts['proj']
    new_seq = opts['seq']
    out_file = opts['out']
    rough = not opts['precise']
    new_clips = []
    a_clips = next(read_spines(all_subs, authors, opts))
    for a_clip in a_clips:
        if rough:
            new_clips.append(a_clip)
        else:
            for a_child in a_clip.children:
                new_clips.append(a_child)
    # Remove old spines
    for old_spine in list(new_seq.iter('spine')):
        new_seq.remove(old_spine)
    # Insert spine into sequence
    new_spine = ET.SubElement(new_seq, 'spine')
    for a_clip in new_clips:
        a_clip.update_clip(new_assets)
        a_clip.join_timeline(new_spine)
    # Insert sequence into tree
    for old_seq in list(proj.iter('sequence')):
        proj.remove(old_seq)
    proj.append(new_seq)
    # Write the file
    ET.indent(tree, '  ')
    tree.write(out_file, encoding='utf8')


def stitch(in_srt, in_xml, tmp_xml, authors, new_assets):
    all_subs = pysrt.open(in_srt)
    out_audio = str(tmp_xml['audio'])
    out_video = str(tmp_xml['video'])
    # Open video project
    video_tree = ET.parse(in_xml)
    video_root = video_tree.getroot()
    video_proj = to_project(video_root)
    # Open audio project
    audio_tree = ET.parse(in_xml)
    audio_root = audio_tree.getroot()
    audio_proj = to_project(audio_root)
    # Add author resources
    new_video_assets = update_resources(video_root, new_assets)
    new_audio_assets = update_resources(audio_root, new_assets)
    # Cache original sequence
    seq_video = to_sequence(video_proj)
    seq_audio = to_sequence(audio_proj)
    # Video spine with rough cuts
    opts_video = {
        'tree': video_tree,
        'proj': video_proj,
        'seq': seq_video,
        'out': out_video,
        'precise': False,
        'fps': 30
    }
    write_spines(all_subs, authors, new_video_assets, opts_video)
    # Audio spine with precise cuts
    opts_audio = {
        'tree': audio_tree,
        'proj': audio_proj,
        'seq': seq_audio,
        'out': out_audio,
        'precise': True,
        'fps': 30
    }
    write_spines(all_subs, authors, new_audio_assets, opts_audio)


def otioconvert(tmp_xml, out_otio):
    out_str = str(out_otio)
    in_video = str(tmp_xml['video'])
    in_audio = str(tmp_xml['audio'])
    t_video = otio.adapters.read_from_file(in_video, "fcpx_xml")
    t_audio = otio.adapters.read_from_file(in_audio, "fcpx_xml")
    video_tracks = t_video[0].tracks
    audio_tracks = t_audio[0].tracks
    video_track_0 = video_tracks[0]
    audio_track_0 = audio_tracks[0]
    audio_track_0.kind = "Audio"
    name = t_video.name
    video_tracks.clear()
    audio_tracks.clear()
    t = otio.schema.SerializableCollection(name)
    t.append(otio.schema.Timeline(name))
    # Join the audio and video tracks
    t[0].tracks = otio.schema.Stack()
    t[0].tracks.append(video_track_0)
    t[0].tracks.append(audio_track_0)
    otio.adapters.write_to_file(t, out_str)
    print(f'Converted {out_otio}')


if __name__ == "__main__":
    fname = 'dev_tools_game_0'
    in_srt = Path(f'./{fname}.srt')
    in_xml = Path(f'./{fname}.fcpxml')
    tmp_xml_root = Path('./tmp_fcpxml')
    tmp_xml = {
        'video': tmp_xml_root / Path(f'{fname}_video.fcpxml'),
        'audio': tmp_xml_root / Path(f'{fname}_audio.fcpxml')
    }
    out_otio = Path(f'./{fname}_out.otio')
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
    new_assets = [{
        'ref': None,
        'name': 'Adam',
        'old': '2022-05-05_20-15-08-1.mp4',
        'path': '2022-05-05_20-15-08-adam.mp4'
    }, {
        'ref': None,
        'name': 'Adam',
        'old': '2022-05-12_20-36-59.mp4',
        'path': '2022-05-12_20-36-59-adam.mp4'
    }]
    tmp_xml_root.mkdir(parents=True, exist_ok=True)
    stitch(in_srt, in_xml, tmp_xml, authors, new_assets)
    otioconvert(tmp_xml, out_otio)
