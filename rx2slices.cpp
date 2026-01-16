#include <iostream>
#include <vector>
#include <string>
#include <fstream>
#include <cmath>
#include <iomanip>
#include <algorithm>
#include <sys/stat.h>

// Platform detection
#if defined(_WIN32) || defined(__WIN32__) || defined(WIN32)
    #define REX_PLATFORM_WIN 1
    #include <windows.h>
    #include <direct.h>
    #define mkdir(path, mode) _mkdir(path)
#else
    #define REX_PLATFORM_MAC 1
    #include <CoreFoundation/CoreFoundation.h>
    #include <unistd.h>
#endif

extern "C" {
    #include "REX.h"
    #include "Wav.h"
}

using namespace std;

const int PREVIEW_LATENCY_COMPENSATION = -64;

// ---------------------------------------------------------------------
// Octatrack Metadata Class
// ---------------------------------------------------------------------
class OctatrackMetadata {
public:
    struct Slice {
        uint32_t start;
        uint32_t end;
    };

    uint32_t tempo_val;
    uint32_t trim_len;
    uint32_t trim_end;
    vector<Slice> slices;

    OctatrackMetadata(double bpm, int sampleRate, int totalFrames) {
        tempo_val = (uint32_t)(bpm * 24.0);
        double bars = floor(((bpm * (double)totalFrames) / ((double)sampleRate * 60.0 * 4.0)) + 0.5);
        trim_len = (uint32_t)(bars * 25.0);
        trim_end = (uint32_t)totalFrames;
    }

    void addSlice(uint32_t start, uint32_t end) {
        if (slices.size() < 64) {
            slices.push_back({start, end});
        }
    }

    vector<uint8_t> getBuffer() const {
        vector<uint8_t> buffer(832, 0);
        uint8_t header[] = { 0x46, 0x4F, 0x52, 0x4D, 0x00, 0x00, 0x00, 0x00, 0x44, 0x50, 0x53, 0x31, 0x53, 0x4D, 0x50, 0x41 };
        for(int i=0; i<16; ++i) buffer[i] = header[i];
        uint8_t unknown[] = { 0x00, 0x00, 0x00, 0x00, 0x00, 0x02, 0x00 };
        for(int i=0; i<7; ++i) buffer[16+i] = unknown[i];

        write32BE(buffer, 23, tempo_val);
        write32BE(buffer, 27, trim_len); 
        write32BE(buffer, 31, trim_len); 
        write32BE(buffer, 35, 0);        
        write32BE(buffer, 39, 0);        
        write16BE(buffer, 43, 48);       
        buffer[45] = 0xFF;               
        write32BE(buffer, 46, 0);        
        write32BE(buffer, 50, trim_end); 
        write32BE(buffer, 54, 0);        

        for (size_t i = 0; i < 64; ++i) {
            int offset = 58 + (i * 12);
            if (i < slices.size()) {
                write32BE(buffer, offset, slices[i].start);
                write32BE(buffer, offset + 4, slices[i].end);
                write32BE(buffer, offset + 8, 0xFFFFFFFF);
            }
        }
        write32BE(buffer, 826, (uint32_t)slices.size());
        uint16_t checksum = 0;
        for (int i = 16; i <= 829; ++i) checksum += buffer[i];
        write16BE(buffer, 830, checksum);
        return buffer;
    }

private:
    static void write32BE(vector<uint8_t>& b, int pos, uint32_t val) {
        b[pos] = (val >> 24) & 0xFF; b[pos+1] = (val >> 16) & 0xFF;
        b[pos+2] = (val >> 8) & 0xFF; b[pos+3] = val & 0xFF;
    }
    static void write16BE(vector<uint8_t>& b, int pos, uint16_t val) {
        b[pos] = (val >> 8) & 0xFF; b[pos+1] = val & 0xFF;
    }
};

// ---------------------------------------------------------------------
// Path Helpers
// ---------------------------------------------------------------------
struct FilePaths {
    string baseName;
    string wavPath;
    string metaPath;
};

FilePaths DerivePaths(const string& inputPath, bool useOcta) {
    FilePaths p;
    size_t last_slash = inputPath.find_last_of("\\/");
    string dir = (last_slash == string::npos) ? "." : inputPath.substr(0, last_slash);
    string fileWithExt = (last_slash == string::npos) ? inputPath : inputPath.substr(last_slash + 1);
    
    size_t last_dot = fileWithExt.find_last_of(".");
    p.baseName = (last_dot == string::npos) ? fileWithExt : fileWithExt.substr(0, last_dot);

    p.wavPath = dir + "/" + p.baseName + ".wav";

    if (useOcta) {
        // .ot file in the same directory as .wav
        p.metaPath = dir + "/" + p.baseName + ".ot";
    } else {
        // .slices file in the .slices/ subdirectory
        string slicesDir = dir + "/.slices";
        mkdir(slicesDir.c_str(), 0777);
        p.metaPath = slicesDir + "/" + p.baseName + ".slices";
    }

    return p;
}

#if REX_PLATFORM_WIN
wstring ConvertToWide(const string& str) {
    int len = MultiByteToWideChar(CP_UTF8, 0, str.c_str(), -1, NULL, 0);
    wstring wstr(len, L'\0');
    MultiByteToWideChar(CP_UTF8, 0, str.c_str(), -1, &wstr[0], len);
    if (!wstr.empty() && wstr.back() == L'\0') wstr.pop_back();
    return wstr;
}
#endif

// ---------------------------------------------------------------------
// Main
// ---------------------------------------------------------------------
int main(int argc, char** argv) {
    string rx2Path = "";
    bool useOcta = false;

    if (argc < 2) {
        cerr << "Usage: " << argv[0] << " [-octa] input.rx2" << endl;
        return 1;
    }

    for (int i = 1; i < argc; ++i) {
        string arg = argv[i];
        if (arg == "-octa") useOcta = true;
        else rx2Path = arg;
    }

    if (rx2Path.empty()) {
        cerr << "Error: No input file specified." << endl;
        return 1;
    }

    FilePaths paths = DerivePaths(rx2Path, useOcta);
    
    string exePath = argv[0];
    size_t last_slash = exePath.find_last_of("\\/");
    string sdkPath = (last_slash == string::npos) ? "." : exePath.substr(0, last_slash);

    ifstream file(rx2Path, ios::binary);
    if (!file) { cerr << "Error: Cannot open " << rx2Path << endl; return 1; }
    file.seekg(0, ios::end);
    size_t fileSize = file.tellg();
    file.seekg(0);
    vector<char> rx2Buf(fileSize);
    file.read(rx2Buf.data(), fileSize);
    file.close();

#if REX_PLATFORM_WIN
    REX::REXInitializeDLL_DirPath(ConvertToWide(sdkPath).c_str());
#else
    REX::REXInitializeDLL_DirPath(sdkPath.c_str());
#endif

    REX::REXHandle handle = nullptr;
    REX::REXCreate(&handle, rx2Buf.data(), (int)fileSize, nullptr, nullptr);

    REX::REXInfo info;
    REX::REXGetInfo(handle, sizeof(info), &info);
    REX::REXSetOutputSampleRate(handle, info.fSampleRate);
    REX::REXGetInfo(handle, sizeof(info), &info);

    double bpm = (double)info.fTempo / 1000.0;
    double exactLen = (double)info.fSampleRate * 1000.0 * (double)info.fPPQLength / ((double)info.fTempo * 256.0);
    int lengthFrames = (int)round(exactLen);

    float* renderSamples = (float*)malloc(info.fChannels * lengthFrames * sizeof(float));
    float* renderBuffers[2] = { &renderSamples[0], (info.fChannels == 2) ? &renderSamples[lengthFrames] : nullptr };

    REX::REXSetPreviewTempo(handle, info.fTempo);
    REX::REXStartPreview(handle);
    int framesRendered = 0;
    while (framesRendered < lengthFrames) {
        int todo = min(64, lengthFrames - framesRendered);
        float* batch[2] = { renderBuffers[0] + framesRendered, renderBuffers[1] ? renderBuffers[1] + framesRendered : nullptr };
        REX::REXRenderPreviewBatch(handle, todo, batch);
        framesRendered += todo;
    }
    REX::REXStopPreview(handle);

    // Save WAV
    FILE* wavFile = fopen(paths.wavPath.c_str(), "wb");
    if (wavFile) {
        WriteWave(wavFile, lengthFrames, info.fChannels, 16, info.fSampleRate, renderBuffers);
        fclose(wavFile);
        cout << "Exported Audio: " << paths.wavPath << endl;
    }

    // Save Metadata
    if (useOcta) {
        OctatrackMetadata ot(bpm, info.fSampleRate, lengthFrames);
        for (int i = 0; i < info.fSliceCount; i++) {
            REX::REXSliceInfo s;
            REX::REXGetSliceInfo(handle, i, sizeof(s), &s);
            int start = max(0, (int)round(((double)s.fPPQPos / info.fPPQLength) * lengthFrames) + PREVIEW_LATENCY_COMPENSATION);
            int end = lengthFrames - 1;
            if (i < info.fSliceCount - 1) {
                REX::REXSliceInfo next;
                REX::REXGetSliceInfo(handle, i+1, sizeof(next), &next);
                end = max(0, (int)round(((double)next.fPPQPos / info.fPPQLength) * lengthFrames) + PREVIEW_LATENCY_COMPENSATION - 1);
            }
            ot.addSlice((uint32_t)start, (uint32_t)end);
        }
        vector<uint8_t> otBuf = ot.getBuffer();
        ofstream ofs(paths.metaPath, ios::binary);
        if (ofs) {
            ofs.write((char*)otBuf.data(), otBuf.size());
            cout << "Exported OT: " << paths.metaPath << endl;
        }
    } else {
        ofstream xml(paths.metaPath);
        if (xml) {
            xml << "<?xml version=\"1.0\" encoding=\"UTF-8\" standalone=\"yes\"?>\n";
            xml << "<audio filename=\"" << paths.baseName << ".wav\">\n";
            for (int i = 0; i < info.fSliceCount; i++) {
                REX::REXSliceInfo s;
                REX::REXGetSliceInfo(handle, i, sizeof(s), &s);
                int start = max(0, (int)round(((double)s.fPPQPos / info.fPPQLength) * lengthFrames) + PREVIEW_LATENCY_COMPENSATION);
                xml << "       <slice start=\"" << fixed << setprecision(6) << (double)start/info.fSampleRate << "\" />\n";
            }
            xml << "</audio>\n";
            cout << "Exported Slices: " << paths.metaPath << endl;
        }
    }

    free(renderSamples);
    REX::REXDelete(&handle);
    REX::REXUninitializeDLL();
    return 0;
}
