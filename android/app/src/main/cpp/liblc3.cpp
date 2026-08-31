#include <jni.h>

#include <cstdint>
#include <limits>
#include <new>
#include <vector>

#include "include/rnnoise.h"
#include "lc3_decoder_core.h"

namespace {

jbyteArray emptyByteArray(JNIEnv* env) {
    return env->NewByteArray(0);
}

}  // namespace

extern "C" JNIEXPORT jbyteArray JNICALL
Java_com_example_demo_1ai_1even_cpp_Cpp_decodeLC3(
    JNIEnv* env,
    jclass,
    jbyteArray lc3Data
) {
    if (lc3Data == nullptr) {
        return emptyByteArray(env);
    }

    const jsize encodedLength = env->GetArrayLength(lc3Data);
    if (
        encodedLength <= 0 ||
        !hepta::audio::isValidLc3PayloadLength(
            static_cast<std::size_t>(encodedLength)
        )
    ) {
        return emptyByteArray(env);
    }

    try {
        std::vector<std::uint8_t> encoded(
            static_cast<std::size_t>(encodedLength)
        );
        env->GetByteArrayRegion(
            lc3Data,
            0,
            encodedLength,
            reinterpret_cast<jbyte*>(encoded.data())
        );
        if (env->ExceptionCheck()) {
            return nullptr;
        }

        const std::vector<std::uint8_t> decoded =
            hepta::audio::decodeLc3Payload(
                encoded.data(),
                encoded.size()
            );
        if (decoded.empty()) {
            return emptyByteArray(env);
        }
        if (
            decoded.size() >
            static_cast<std::size_t>(
                std::numeric_limits<jsize>::max()
            )
        ) {
            return emptyByteArray(env);
        }

        const auto decodedLength =
            static_cast<jsize>(decoded.size());
        jbyteArray result = env->NewByteArray(decodedLength);
        if (result == nullptr) {
            return nullptr;
        }
        env->SetByteArrayRegion(
            result,
            0,
            decodedLength,
            reinterpret_cast<const jbyte*>(decoded.data())
        );
        if (env->ExceptionCheck()) {
            return nullptr;
        }
        return result;
    } catch (const std::bad_alloc&) {
        return emptyByteArray(env);
    } catch (...) {
        return emptyByteArray(env);
    }
}

extern "C" JNIEXPORT jfloatArray JNICALL
Java_com_example_demo_1ai_1even_cpp_Cpp_rnNoise(
    JNIEnv* env,
    jclass,
    jlong state,
    jfloatArray input
) {
    if (
        state == 0 ||
        input == nullptr ||
        env->GetArrayLength(input) != 480
    ) {
        return nullptr;
    }
    jfloat* inputArray =
        env->GetFloatArrayElements(input, nullptr);
    if (inputArray == nullptr) {
        return nullptr;
    }
    rnnoise_process_frame(
        reinterpret_cast<DenoiseState*>(state),
        inputArray,
        inputArray
    );
    env->ReleaseFloatArrayElements(input, inputArray, 0);
    return input;
}

extern "C" JNIEXPORT jlong JNICALL
Java_com_example_demo_1ai_1even_cpp_Cpp_createRNNoiseState(
    JNIEnv*,
    jclass
) {
    return reinterpret_cast<jlong>(rnnoise_create(nullptr));
}

extern "C" JNIEXPORT void JNICALL
Java_com_example_demo_1ai_1even_cpp_Cpp_destroyRNNoiseState(
    JNIEnv*,
    jclass,
    jlong state
) {
    if (state != 0) {
        rnnoise_destroy(reinterpret_cast<DenoiseState*>(state));
    }
}
