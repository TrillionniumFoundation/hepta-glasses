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

    func testGenerationNTokenCannotOwnGenerationNPlusOne() {
        let authority = ConnectionAttemptAuthority()
        let peripheralID = UUID()
        let old = authority.begin(
            peripheralID: peripheralID,
            side: .left,
            generation: 40,
            nonce: UUID(uuidString: "00000000-0000-0000-0000-000000000040")!
        )
        let current = authority.begin(
            peripheralID: peripheralID,
            side: .left,
            generation: 41,
            nonce: UUID(uuidString: "00000000-0000-0000-0000-000000000041")!
        )

        XCTAssertFalse(authority.owns(old))
        XCTAssertTrue(authority.owns(current))
        XCTAssertFalse(authority.retire(old))
        XCTAssertTrue(authority.owns(current))
    }

    func testUnknownPeripheralCannotFallThroughToRightLeg() {
        let authority = ConnectionAttemptAuthority()
        let selectedID = UUID()
        let unknownID = UUID()
        let selected = authority.begin(
            peripheralID: selectedID,
            side: .right,
            generation: 7
        )
        let forgedUnknown = PeripheralAttemptToken(
            peripheralID: unknownID,
            side: .right,
            generation: 7,
            nonce: UUID()
        )

        XCTAssertTrue(authority.owns(selected))
        XCTAssertFalse(authority.owns(forgedUnknown))
        XCTAssertNil(authority.token(for: unknownID))
    }

    func testRetiredPeripheralBlocksReuseUntilTerminalCallbackConsumed() {
        let barrier = RetiredConnectionBarrier()
        let retiredID = UUID()
        let otherID = UUID()
        barrier.insert(retiredID)

        XCTAssertTrue(barrier.contains(retiredID))
        XCTAssertTrue(barrier.blocks(any: [retiredID, otherID]))
        XCTAssertFalse(barrier.blocks(any: [otherID]))
        XCTAssertTrue(barrier.consume(retiredID))
        XCTAssertFalse(barrier.contains(retiredID))
        XCTAssertFalse(barrier.consume(retiredID))
    }

    func testRetiringOneAttemptDoesNotRetireOppositeLeg() {
        let authority = ConnectionAttemptAuthority()
        let left = authority.begin(
            peripheralID: UUID(),
            side: .left,
            generation: 9
        )
        let right = authority.begin(
            peripheralID: UUID(),
            side: .right,
            generation: 9
        )

        XCTAssertTrue(authority.retire(left))
        XCTAssertFalse(authority.owns(left))
        XCTAssertTrue(authority.owns(right))
    }
}
