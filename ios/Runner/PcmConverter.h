#import <Foundation/Foundation.h>

NS_ASSUME_NONNULL_BEGIN

@interface PcmConverter : NSObject

- (NSMutableData *)decode:(NSData *)lc3Data;
- (void)reset;

@end

NS_ASSUME_NONNULL_END
