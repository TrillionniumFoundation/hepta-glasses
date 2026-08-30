import Flutter
import UIKit
import XCTest
@testable import Runner

final class RunnerTests: XCTestCase {
    func testPcmConverterRejectsTruncatedFrame() {
        let converter = PcmConverter()
        XCTAssertEqual(converter.decode(Data(repeating: 0, count: 19)).count, 0)
    }

    func testPcmConverterRejectsOversizedPayload() {
        let converter = PcmConverter()
        XCTAssertEqual(converter.decode(Data(repeating: 0, count: 4_100)).count, 0)
    }

    func testPcmConverterRejectsNonIntegralFrameCount() {
        let converter = PcmConverter()
        XCTAssertEqual(converter.decode(Data(repeating: 0, count: 21)).count, 0)
    }
}
