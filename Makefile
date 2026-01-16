# --- SDK Path Configuration ---
REX_SDK_DIR = ./REXSDK_Mac_1.9.2

# 1. Use backslashes to escape spaces for Make's dependency parser
WAV_DIR_ESC = $(REX_SDK_DIR)/REX\ Test\ App
WAV_C_ESC   = $(WAV_DIR_ESC)/Wav.c
REX_C_ESC   = $(REX_SDK_DIR)/REX.c

TARGET = rx2slices 

# --- Platform Detection & Compiler Setup ---
ifeq ($(OS),Windows_NT)
    EXE      = $(TARGET).exe
    CXX      = x86_64-w64-mingw32-g++
    CC       = x86_64-w64-mingw32-gcc
    RM       = del /Q
    
    # Use quotes for paths in flags to handle spaces in the shell
    INC_FLAGS = -I"$(REX_SDK_DIR)" -I"$(REX_SDK_DIR)/REX Test App"
    
    DEFINES   = -DREX_WINDOWS=1 -DREX_MAC=0 -DREX_DLL_LOADER=1 \
                -DREX_TYPES_DEFINED -DREX_int32_t=int
    
    CFLAGS    = $(INC_FLAGS) $(DEFINES) -O2
    CXXFLAGS  = $(CFLAGS) -std=c++17
    LDFLAGS   = -static -static-libstdc++ -static-libgcc -lversion
else
    EXE      = $(TARGET)
    CXX      = clang++
    CC       = clang
    RM       = rm -f
    
    ARCH_FLG  = -arch arm64
    # ARCH_FLG = -arch x86_64
    
    INC_FLAGS = -I"$(REX_SDK_DIR)" -I"$(REX_SDK_DIR)/REX Test App"
    
    DEFINES   = -DREX_MAC=1 -DREX_WINDOWS=0 -DREX_DLL_LOADER=1
    
    CFLAGS    = $(ARCH_FLG) $(INC_FLAGS) $(DEFINES) -O2
    CXXFLAGS  = $(CFLAGS) -std=c++17
    LDFLAGS   = $(ARCH_FLG) -framework CoreFoundation
endif

# --- Build Targets ---
OBJS = rx2slices.o REX.o Wav.o

all: $(EXE)

# Final Link
$(EXE): $(OBJS)
	$(CXX) $(OBJS) -o $(EXE) $(LDFLAGS)

# Compile C++ source
rx2slices.o: rx2slices.cpp
	$(CXX) $(CXXFLAGS) -c $< -o $@

# Compile REX.c
REX.o: $(REX_C_ESC)
	$(CC) $(CFLAGS) -c "$<" -o $@

# Compile Wav.c (using the escaped path for the dependency)
Wav.o: $(WAV_C_ESC)
	$(CC) $(CFLAGS) -c "$<" -o $@

clean:
	$(RM) *.o $(EXE)

.PHONY: all clean
