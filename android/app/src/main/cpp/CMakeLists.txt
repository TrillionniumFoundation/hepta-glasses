cmake_minimum_required(VERSION 3.22.1)

project("lc3")

include_directories(include)

add_library(${CMAKE_PROJECT_NAME} SHARED
        liblc3.cpp
        lc3_decoder_core.cpp

        liblc3/attdet.c
        liblc3/bits.c
        liblc3/bwdet.c
        liblc3/energy.c
        liblc3/lc3.c
        liblc3/ltpf.c
        liblc3/mdct.c
        liblc3/plc.c
        liblc3/sns.c
        liblc3/spec.c
        liblc3/tables.c
        liblc3/tns.c

        rnnoise/celt_lpc.c
        rnnoise/denoise.c
        rnnoise/kiss_fft.c
        rnnoise/pitch.c
        rnnoise/rnn.c
        rnnoise/rnn_data.c
        rnnoise/rnn_reader.c
)

target_compile_features(${CMAKE_PROJECT_NAME} PRIVATE cxx_std_17)

target_link_libraries(${CMAKE_PROJECT_NAME}
        android
        log)
