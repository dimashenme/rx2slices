import os
import subprocess
import zipfile
import argparse
import math
import wave
import shutil
import sys
import xml.etree.ElementTree as ET
from xml.dom import minidom
import os.path as osp
import numpy as np
from sklearn.linear_model import LinearRegression
from sklearn.cluster import DBSCAN

# --- CONFIGURATION CONSTANTS ---
DEFAULT_BPM = 100.0
MIN_BPM = 60.0
MAX_BPM = 170.0
BPM_STEP = 0.1
KERNEL_SIGMA = 0.02         # Gaussian variance for BPM alignment
BPM_PERCENTILE = 98.0       # Threshold percentile for correlation filtering
CLUSTER_EPS = 4.0           # Max distance between BPM points in the same cluster

def find_rx2slices():
    executable = "rx2slices"
    if sys.platform == "win32":
        executable += ".exe"

    script_dir = osp.dirname(osp.abspath(__file__))
    local_path = osp.join(script_dir, executable)
    if osp.isfile(local_path) and os.access(local_path, os.X_OK):
        return local_path

    path_executable = shutil.which("rx2slices")
    if path_executable:
        return path_executable
    return None

def estimate_bpm(slice_starts, suggestion=None, debug=False):
    """
    Finds optimal BPM by clustering high-correlation bpms.
    If a suggestion is provided, picks the cluster closest to it.
    """
    if not slice_starts:
        return suggestion if suggestion else DEFAULT_BPM

    slices = np.array(slice_starts)
    bpm_range = np.arange(MIN_BPM, MAX_BPM + BPM_STEP, BPM_STEP)
    correlations = []

    for bpm in bpm_range:
        d = 15.0 / bpm
        offsets = (slices % d)
        offsets = np.where(offsets > d/2, offsets - d, offsets)
        corr = np.mean(np.exp(-(offsets**2) / (2 * KERNEL_SIGMA**2)))
        correlations.append(corr)

    correlations = np.array(correlations)
    threshold = np.percentile(correlations, BPM_PERCENTILE)
    mask = correlations >= threshold
    high_corr_bpms = bpm_range[mask].reshape(-1, 1)
    high_corr_vals = correlations[mask]
    
    if len(high_corr_bpms) == 0:
        return suggestion if suggestion else bpm_range[np.argmax(correlations)]

    clustering = DBSCAN(eps=CLUSTER_EPS, min_samples=1).fit(high_corr_bpms)
    labels = clustering.labels_
    n_clusters = len(set(labels))

    cluster_peaks = []
    for i in range(n_clusters):
        m = (labels == i)
        idx_in_cluster = np.argmax(high_corr_vals[m])
        peak_bpm = high_corr_bpms[m][idx_in_cluster][0]
        peak_corr = high_corr_vals[m][idx_in_cluster]
        cluster_peaks.append((peak_bpm, peak_corr))

    if debug:
        info = [f"{round(b,2)} (corr: {round(c,4)})" for b, c in cluster_peaks]
        print(f"  [BPM Debug] Clusters found: {info}")

    if suggestion:
        best_bpm = min(cluster_peaks, key=lambda x: abs(x[0] - suggestion))[0]
    else:
        best_bpm = max(cluster_peaks, key=lambda x: x[1])[0]

    return round(best_bpm, 2)

def estimate_swing(slice_starts, bpm):
    """
    Estimates swing by assuming the grid starts at the first slice.
    Swing=1.0 corresponds to a shift of 1/32nd note for odd grid elements.
    """
    if not slice_starts:
        return 0.0
    
    slices = np.array(slice_starts)
    d = 15.0 / bpm
    anchor = slices[0]
    
    # Indices relative to the first slice
    n_indices = np.round((slices - anchor) / d).astype(int)
    is_odd = (n_indices % 2).astype(float)
    
    # Residual error relative to straight grid
    Y = slices - (anchor + n_indices * d)
    X = (is_odd * (d / 2.0)).reshape(-1, 1)
    
    model = LinearRegression(fit_intercept=False).fit(X, Y)
    swing = model.coef_[0]
    
    return np.clip(swing, 0.0, 1.0)

class DAWProjectGenerator:
    def __init__(self, include_16ths=False, snap_threshold=0.05, debug=False):
        self.tracks = []
        self.id_counter = 100
        self.include_16ths = include_16ths
        self.snap_threshold = snap_threshold
        self.debug = debug

    def get_id(self):
        self.id_counter += 1
        return f"id{self.id_counter}"

    def add_track(self, wav_path, slice_starts, info, suggestion=None):
        if self.debug: print(f"--- Analyzing {osp.basename(wav_path)} ---")
        
        bpm = estimate_bpm(slice_starts, suggestion, self.debug)
        swing = estimate_swing(slice_starts, bpm)
        
        d = 15.0 / bpm 
        first_slice_offset = slice_starts[0] if slice_starts else 0.0
        
        # Grid is now anchored to the first slice start
        end_raw_index = round((info['dur'] - first_slice_offset) / d)
        
        warp_markers = []
        total_grid_error = 0.0

        for i, s in enumerate(slice_starts):
            raw_index = round((s - first_slice_offset) / d)
            swing_index_offset = (raw_index % 2) * (swing * 0.5)
            
            # Theoretical time including swing relative to anchor
            theoretical_time = first_slice_offset + (raw_index + swing_index_offset) * d
            
            time_error = abs(s - theoretical_time)
            total_grid_error += (time_error / d)
            
            if time_error <= self.snap_threshold:
                if (raw_index % 2 == 0) or self.include_16ths:
                    # beat_pos is shifted by swing relative to the first slice (beat 0)
                    beat_pos = (raw_index + swing_index_offset) / 4.0
                    warp_markers.append({"beat": beat_pos, "seconds": s})

        final_clip_beats = math.ceil(end_raw_index) / 4.0
        
        print(f"File: {osp.basename(wav_path)}")
        print(f"  > Selected BPM:   {bpm:.2f} (Total Error: {total_grid_error:.4f} 1/16ths)")
        print(f"  > Swing: {swing:.2f}")
        
        self.tracks.append({
            "name": osp.basename(wav_path), "wav_path": wav_path,
            "bpm": bpm, "swing": swing,
            "warp_markers": warp_markers, "first_slice_offset": first_slice_offset,
            "clip_duration_beats": float(max(1.0, final_clip_beats)),
            "file_duration": info['dur'], "sample_rate": info['sr'],
            "channels": info['chans'], "track_id": self.get_id(), "channel_id": self.get_id()
        })

    def build_project_xml(self, global_bpm):
        root = ET.Element("Project", version="1.0")
        ET.SubElement(root, "Application", name="rx2bitwig", version="1.0")
        transport = ET.SubElement(root, "Transport")
        ET.SubElement(transport, "Tempo", value=str(global_bpm), id="id0", name="Tempo")
        ET.SubElement(transport, "TimeSignature", denominator="4", numerator="4", id="id1")

        struct = ET.SubElement(root, "Structure")
        for t in self.tracks:
            track = ET.SubElement(struct, "Track", contentType="audio", loaded="true", id=t["track_id"], name=t["name"])
            chan = ET.SubElement(track, "Channel", audioChannels=str(t["channels"]), destination="master_chan", id=t["channel_id"])
            ET.SubElement(chan, "Volume", value="1.0", id=self.get_id(), name="Volume")

        master = ET.SubElement(struct, "Track", contentType="audio notes", loaded="true", id="master_track", name="Master")
        ET.SubElement(master, "Channel", audioChannels="2", role="master", id="master_chan")

        arr = ET.SubElement(root, "Arrangement", id="arr_id")
        arr_lanes = ET.SubElement(arr, "Lanes", timeUnit="beats")
        for t in self.tracks:
            ET.SubElement(arr_lanes, "Lanes", track=t["track_id"], id=self.get_id())

        scenes = ET.SubElement(root, "Scenes")
        scene = ET.SubElement(scenes, "Scene", id="scene0", name="Scene 1")
        scene_lanes = ET.SubElement(scene, "Lanes", id="lanes_id")
        
        for t in self.tracks:
            slot = ET.SubElement(scene_lanes, "ClipSlot", hasStop="true", track=t["track_id"], id=self.get_id())
            duration_str = str(t["clip_duration_beats"])
            clip = ET.SubElement(slot, "Clip", time="0.0", duration=duration_str, name=t["name"])
            clips_inner = ET.SubElement(clip, "Clips")
            clip_event = ET.SubElement(clips_inner, "Clip", time=str(-t["first_slice_offset"]), duration=duration_str, contentTimeUnit="beats")
            warps = ET.SubElement(clip_event, "Warps", contentTimeUnit="seconds", timeUnit="beats")
            audio_tag = ET.SubElement(warps, "Audio", channels=str(t["channels"]), sampleRate=str(t["sample_rate"]), duration=str(t["file_duration"]), id=self.get_id())
            ET.SubElement(audio_tag, "File", path=f"audio/{osp.basename(t['wav_path'])}")

            for m in t["warp_markers"]:
                ET.SubElement(warps, "Warp", time=str(m["beat"]), contentTime=str(m["seconds"]))
            ET.SubElement(warps, "Warp", time=duration_str, contentTime=str(t["file_duration"]))

        raw_xml = ET.tostring(root, encoding="utf-8")
        return minidom.parseString(raw_xml).toprettyxml(indent="  ")

    def save(self, output_path, bpm_override=None):
        if not self.tracks: return
        global_bpm = bpm_override if bpm_override else max(t["bpm"] for t in self.tracks)
        with zipfile.ZipFile(output_path, 'w') as zipf:
            zipf.writestr("metadata.xml", '<?xml version="1.0" encoding="UTF-8" standalone="yes"?><MetaData/>')
            zipf.writestr("project.xml", self.build_project_xml(global_bpm))
            for t in self.tracks:
                zipf.write(t["wav_path"], f"audio/{osp.basename(t['wav_path'])}")
        print(f"Created DAWProject: {output_path} at {global_bpm} BPM")

class MultisampleGenerator:
    def __init__(self, wav_path, sample_rate, total_frames):
        self.wav_path = wav_path
        self.sample_rate = sample_rate
        self.total_frames = total_frames
        self.slices = []

    def add_slice(self, start_sec):
        self.slices.append(start_sec)

    def _generate_xml(self):
        name = osp.splitext(osp.basename(self.wav_path))[0]
        root = ET.Element("multisample", name=name)
        midi_note = 36
        for start_sec in sorted(self.slices):
            start_frame = start_sec * self.sample_rate
            sample_node = ET.SubElement(root, "sample", {
                "file": osp.basename(self.wav_path),
                "sample-start": f"{start_frame:.3f}",
                "sample-stop": f"{self.total_frames:.3f}",
                "zone-logic": "always-play"
            })
            ET.SubElement(sample_node, "key", {"high": str(midi_note), "low": str(midi_note), "root": "60", "track": "0.0000"})
            ET.SubElement(sample_node, "loop", {"mode": "off", "start": f"{start_frame:.3f}", "stop": f"{self.total_frames:.3f}"})
            midi_note = min(midi_note + 1, 127)
        raw_str = ET.tostring(root, encoding="utf-8")
        return minidom.parseString(raw_str).toprettyxml(indent="   ")

    def save(self):
        output_path = osp.splitext(self.wav_path)[0] + ".multisample"
        with zipfile.ZipFile(output_path, 'w') as zipf:
            zipf.writestr("multisample.xml", self._generate_xml())
            zipf.write(self.wav_path, osp.basename(self.wav_path))
        print(f"Created Multisample: {output_path}")

def get_wav_info(wav_path):
    with wave.open(wav_path, 'rb') as w:
        frames, rate = w.getnframes(), w.getframerate()
        return {'dur': frames / float(rate), 'sr': rate, 'chans': w.getnchannels(), 'frames': frames}

def parse_file_arg(arg):
    if ":" in arg:
        parts = arg.split(":")
        filename = ":".join(parts[:-1])
        try:
            return filename, float(parts[-1])
        except ValueError:
            return arg, None
    return arg, None

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Process WAV/RX2 to DAWProject or Multisample")
    parser.add_argument("files", nargs="*", help="Files (optionally filename:bpm)")
    parser.add_argument("-l", "--list", help="File containing list of files")
    parser.add_argument("-o", "--output", default="Export.dawproject", help="Output DAWProject name")
    parser.add_argument("-b", "--bpm", type=float, help="Override global BPM")
    parser.add_argument("--ms", action="store_true", help="Export as .multisample")
    parser.add_argument("--all-markers", action="store_true", help="Keep 1/16th markers")
    parser.add_argument("--debug", action="store_true", help="Verbose debug")
    
    args = parser.parse_args()
    rx2bin = find_rx2slices()
    daw_gen = DAWProjectGenerator(include_16ths=args.all_markers, debug=args.debug)

    input_data = [parse_file_arg(f) for f in args.files]
    if args.list:
        with open(args.list, 'r') as f:
            for line in f:
                if line.strip(): input_data.append(parse_file_arg(line.strip()))
    
    for f_path, suggestion in input_data:
        if f_path.lower().endswith(".rx2"):
            if not rx2bin: continue
            subprocess.run([rx2bin, f_path], check=True)
            wav = osp.splitext(f_path)[0] + ".wav"
        else:
            wav = f_path
            
        slices_path = osp.join(osp.dirname(wav), ".slices", osp.splitext(osp.basename(wav))[0] + ".slices")

        if osp.exists(wav) and osp.exists(slices_path):
            tree = ET.parse(slices_path)
            slice_starts = sorted([float(s.get("start")) for s in tree.findall("slice")])
            info = get_wav_info(wav)
            if args.ms:
                ms_gen = MultisampleGenerator(wav, info['sr'], info['frames'])
                for start in slice_starts: ms_gen.add_slice(start)
                ms_gen.save()
            else:
                daw_gen.add_track(wav, slice_starts, info, suggestion)

    if not args.ms: daw_gen.save(args.output, args.bpm)
