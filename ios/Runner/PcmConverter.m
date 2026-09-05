//
//  PcmConverter.m
//  Runner
//
//  Stateful LC3 decoder with strict frame validation and bounded allocations.
//

#import "PcmConverter.h"
#import "lc3.h"

#include <stdint.h>
#include <stdlib.h>
#include <string.h>

@interface PcmConverter () {
    void *_decoderMemory;
    int16_t *_frameBuffer;
    lc3_decoder_t _decoder;
    int _samplesPerFrame;
}
@end

@implementation PcmConverter

static const int kFrameDurationUs = 10000;
static const int kSampleRateHz = 16000;
static const NSUInteger kEncodedFrameBytes = 20;
static const NSUInteger kMaximumEncodedPayloadBytes = 4000;

- (instancetype)init {
    self = [super init];
    if (self != nil) {
        [self reset];
    }
    return self;
}

- (void)dealloc {
    [self tearDownDecoder];
}

- (void)reset {
    @synchronized (self) {
        [self tearDownDecoder];
        const unsigned decoderSize = lc3_decoder_size(
            kFrameDurationUs,
            kSampleRateHz
        );
        _samplesPerFrame = lc3_frame_samples(
            kFrameDurationUs,
            kSampleRateHz
        );
        if (decoderSize == 0 || _samplesPerFrame <= 0) {
            _samplesPerFrame = 0;
            return;
        }
        _decoderMemory = calloc(1, decoderSize);
        _frameBuffer = calloc(
            (size_t)_samplesPerFrame,
            sizeof(int16_t)
        );
        if (_decoderMemory == NULL || _frameBuffer == NULL) {
            [self tearDownDecoder];
            return;
        }
        _decoder = lc3_setup_decoder(
            kFrameDurationUs,
            kSampleRateHz,
            0,
            _decoderMemory
        );
        if (_decoder == NULL) {
            [self tearDownDecoder];
        }
    }
}

- (NSMutableData *)decode:(NSData *)lc3Data {
    @synchronized (self) {
        if (lc3Data.length == 0 ||
            lc3Data.length > kMaximumEncodedPayloadBytes ||
            lc3Data.length % kEncodedFrameBytes != 0 ||
            _decoder == NULL ||
            _frameBuffer == NULL ||
            _samplesPerFrame <= 0) {
            return [NSMutableData data];
        }

        const NSUInteger frameCount = lc3Data.length / kEncodedFrameBytes;
        const NSUInteger decodedFrameBytes =
            (NSUInteger)_samplesPerFrame * sizeof(int16_t);
        if (frameCount > NSUIntegerMax / decodedFrameBytes) {
            return [NSMutableData data];
        }
        NSMutableData *pcmData = [NSMutableData dataWithCapacity:
            frameCount * decodedFrameBytes];
        const uint8_t *encoded = lc3Data.bytes;
        if (encoded == NULL) {
            return [NSMutableData data];
        }

        for (NSUInteger frame = 0; frame < frameCount; frame++) {
            const uint8_t *input = encoded + frame * kEncodedFrameBytes;
            const int status = lc3_decode(
                _decoder,
                input,
                (int)kEncodedFrameBytes,
                LC3_PCM_FORMAT_S16,
                _frameBuffer,
                1
            );
            if (status < 0) {
                [pcmData setLength:0];
                memset(
                    _frameBuffer,
                    0,
                    decodedFrameBytes
                );
                break;
            }
            [pcmData appendBytes:_frameBuffer length:decodedFrameBytes];
            memset(_frameBuffer, 0, decodedFrameBytes);
        }
        return pcmData;
    }
}

- (void)tearDownDecoder {
    free(_decoderMemory);
    free(_frameBuffer);
    _decoderMemory = NULL;
    _frameBuffer = NULL;
    _decoder = NULL;
    _samplesPerFrame = 0;
}

@end
