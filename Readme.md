# rx2slices and rx2bitwig

`rx2decoder` extracts the audio data and slice information from
ReCycle REX (`.rx2`) files. It can also optionally generate an
.ot file, readable by Elektron Octatrack, containing that slicing
information. 

`rx2bitwig` is a script that I use to import rx2 files into
bitwig. The script generates either a .dawproject file (that Bitwig
can read) from a collection of `.rx2` files, putting the audio files
on separate tracks and converting slice staring points to warp marks,
or a `.multisample` file, spreading different slices across different
multisample zones.

## Building and requirements

You will need Xcode Command Line Tools (`clang++` and `clang`) on
macOS and MinGW-w64 (`x86_64-w64-mingw32-g++`) on Windows.

Download [REX SDK](https://developer.reasonstudios.com/downloads/other-products) and run
```bash
make REX_SDK_DIR=./REXSDK
```

To use `rx2bitwig.py` you need to [install Python](https://www.python.org/downloads/)  then install `numpy` and `scikit-learn`:
```bash
pip install numpy scikit-learn
```

## Usage

Make sure ``REX Shared Library.bundle`` or ``REX Shared Library.dll``
is where rx2slices can find it.

```bash
./rx2slices loop.rx2
```
generates a `loop.wav` in the same directory as the `.rx2` file (and
`.slices/loop.slices` with the slicing information).

```bash
./rx2slices -octa loop.rx2
```
generates a `loop.wav` and a `loop.ot` file, which can be uploaded to
the Octatrack's SD card.


```bash
python rx2bitwig.py loop1.wav loop2.rx2 -o MyProject.dawproject
```
creates a single multi-track project with each piece of audio on a separate
track.

```bash
python rx2bitwig.py loop1.wav loop2.rx2 --ms
```
creates Bitwig `.multisample` instrument files for every input file,
mapping slices to consequtive notes starting from C1.

## Options

| Flag | Description |
| :--- | :--- |
| `-l LIST, --list LIST` | Get a list of file names from a file. |
| `-o FILE, --output FILE` | Name of the output DAWProject (Default: `Export.dawproject`). |
| `-b, --bpm` | Override the DAWProject BPM (default: maximum of BPMs of input files). |
| `--ms` | Export as `.multisample` files instead of a DAWProject. |
| `--all-markers` | Place warp markers for every slice (Default filters to 1/8th note grid). |
| `--debug` | Print some information during BPM detection. |

The script tries to guess the BPM of each audio file and converts
slice starts to warp markers, assuming that the first slice starts on
the `1` of the grid. It snaps the warp markers to the grid. It also
estimates the amount of swing based on where the slice start, and
takes this estimated swing amount into account when snapping the warp
markers to the grid. To help guide the BPM detection, you can suggest
an imprecise value of BPM for each file after a colon, for example

```bash
python rx2bitwig.py loop1.wav:90 loop2.rx2:130
```
## Acknowledgements

`rx2slices.cpp` is based on the code from [Paketti](https://github.com/esaruoho/paketti/) by Esa Juhani Ruoho @esaruoho.
