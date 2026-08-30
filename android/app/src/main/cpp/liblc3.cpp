#include <jni.h>

#include <algorithm>
#include <cstdint>
#include <cstring>
#include <limits>
#include <vector>

#include "include/lc3.h"
#include "include/rnnoise.h"

namespace {
constexpr int kFrameDurationUs = 10000;
constexpr int kSampleRateHz = 16000;
constexpr int kEncodedFrameBytes = 20;
constexpr int kMaximumEncodedPayloadBytes = 4096;

jbyteArray emptyByteArray(JNIEnv *env) {
    return env->NewByteArray(0);
}
}  // namespace

extern "C" JNIEXPORT jbyteArray JNICALL
Java_com_example_demo_1ai_1even_cpp_Cpp_decodeLC3(
    JNIEnv *env,
    jclass,
    jbyteArray lc3Data
) {
    if (lc3Data == nullptr) {
        return emptyByteArray(env);
    }
    const jsize encodedLength = env->GetArrayLength(lc3Data);
    if (encodedLength <= 0 ||
        encodedLength > kMaximumEncodedPayloadBytes ||
        encodedLength % kEncodedFrameBytes != 0) {
        return emptyByteArray(env);
    }

    const unsigned decoderSize = lc3_decoder_size(kFrameDurationUs, kSampleRateHz);
    const int samplesPerFrame = lc3_frame_samples(kFrameDurationUs, kSampleRateHz);
    if (decoderSize == 0 || samplesPerFrame <= 0) {
        return emptyByteArray(env);
    }

    const size_t frameCount =
        static_cast<size_t>(encodedLength / kEncodedFrameBytes);
    const size_t decodedFrameBytes =
        static_cast<size_t>(samplesPerFrame) * sizeof(int16_t);
    if (frameCount >
        std::numeric_limits<size_t>::max() / decodedFrameBytes) {
        return emptyByteArray(env);
    }
    const size_t decodedLength = frameCount * decodedFrameBytes;
    if (decodedLength > static_cast<size_t>(std::numeric_limits<jsize>::max())) {
        return emptyByteArray(env);
    }

    jboolean isCopy = JNI_FALSE;
    jbyte *encodedBytes = env->GetByteArrayElements(lc3Data, &isCopy);
    if (encodedBytes == nullptr) {
        return emptyByteArray(env);
    }

    std::vector<uint8_t> decoderMemory(decoderSize, 0);
    std::vector<int16_t> frameBuffer(static_cast<size_t>(samplesPerFrame), 0);
    std::vector<uint8_t> decoded(decodedLength, 0);
    lc3_decoder_t decoder = lc3_setup_decoder(
        kFrameDurationUs,
        kSampleRateHz,
        0,
        decoderMemory.data()
    );
    if (decoder == nullptr) {
        env->ReleaseByteArrayElements(lc3Data, encodedBytes, JNI_ABORT);
        return emptyByteArray(env);
    }

    bool success = true;
    for (size_t frame = 0; frame < frameCount; frame++) {
        const auto *input = reinterpret_cast<const uint8_t *>(encodedBytes) +
            frame * kEncodedFrameBytes;
        const int status = lc3_decode(
            decoder,
            input,
            kEncodedFrameBytes,
            LC3_PCM_FORMAT_S16,
            frameBuffer.data(),
            1
        );
        if (status < 0) {
            success = false;
            break;
        }
        std::memcpy(
            decoded.data() + frame * decodedFrameBytes,
            frameBuffer.data(),
            decodedFrameBytes
        );
        std::fill(frameBuffer.begin(), frameBuffer.end(), 0);
    }
    env->ReleaseByteArrayElements(lc3Data, encodedBytes, JNI_ABORT);
    if (!success) {
        return emptyByteArray(env);
    }

    jbyteArray result = env->NewByteArray(static_cast<jsize>(decodedLength));
    if (result == nullptr) {
        return nullptr;
    }
    env->SetByteArrayRegion(
        result,
        0,
        static_cast<jsize>(decodedLength),
        reinterpret_cast<const jbyte *>(decoded.data())
    );
    if (env->ExceptionCheck()) {
        return nullptr;
    }
    return result;
}

extern "C" JNIEXPORT jfloatArray JNICALL
Java_com_example_demo_1ai_1even_cpp_Cpp_rnNoise(
    JNIEnv *env,
    jclass,
    jlong state,
    jfloatArray input
) {
    if (state == 0 || input == nullptr || env->GetArrayLength(input) != 480) {
        return nullptr;
    }
    jfloat *inputArray = env->GetFloatArrayElements(input, nullptr);
    if (inputArray == nullptr) {
        return nullptr;
    }
    rnnoise_process_frame(
        reinterpret_cast<DenoiseState *>(state),
        inputArray,
        inputArray
    );
    env->ReleaseFloatArrayElements(input, inputArray, 0);
    return input;
}

extern "C" JNIEXPORT jlong JNICALL
Java_com_example_demo_1ai_1even_cpp_Cpp_createRNNoiseState(
    JNIEnv *,
    jclass
) {
    return reinterpret_cast<jlong>(rnnoise_create(nullptr));
}

extern "C" JNIEXPORT void JNICALL
Java_com_example_demo_1ai_1even_cpp_Cpp_destroyRNNoiseState(
    JNIEnv *,
    jclass,
    jlong state
) {
    if (state != 0) {
        rnnoise_destroy(reinterpret_cast<DenoiseState *>(state));
    }
}
