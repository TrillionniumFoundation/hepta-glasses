import CoreBluetooth
import Flutter

enum GlassesLeg: String, Hashable {
    case left = "L"
    case right = "R"
}

struct PeripheralAttemptToken: Hashable {
    let peripheralID: UUID
    let side: GlassesLeg
    let generation: Int
    let nonce: UUID
}

/// Pure ownership model used by every CBPeripheral delegate callback.
/// A callback may mutate state only while its immutable token is current.
final class ConnectionAttemptAuthority {
    private var currentByPeripheral: [UUID: PeripheralAttemptToken] = [:]

    @discardableResult
    func begin(
        peripheralID: UUID,
        side: GlassesLeg,
        generation: Int,
        nonce: UUID = UUID()
    ) -> PeripheralAttemptToken {
        let token = PeripheralAttemptToken(
            peripheralID: peripheralID,
            side: side,
            generation: generation,
            nonce: nonce
        )
        currentByPeripheral[peripheralID] = token
        return token
    }

    func token(for peripheralID: UUID) -> PeripheralAttemptToken? {
        currentByPeripheral[peripheralID]
    }

    func owns(_ token: PeripheralAttemptToken) -> Bool {
        currentByPeripheral[token.peripheralID] == token
    }

    @discardableResult
    func retire(_ token: PeripheralAttemptToken) -> Bool {
        guard owns(token) else { return false }
        currentByPeripheral[token.peripheralID] = nil
        return true
    }

    func retireAll() -> [PeripheralAttemptToken] {
        let tokens = Array(currentByPeripheral.values)
        currentByPeripheral.removeAll()
        return tokens
    }
}

/// Prevents a CBPeripheral instance from being assigned to a new attempt until
/// the terminal callback for the cancelled attempt has been consumed. This is
/// required because CBCentralManager terminal callbacks do not carry a caller
/// supplied generation token.
final class RetiredConnectionBarrier {
    private var identifiers: Set<UUID> = []

    func insert(_ identifier: UUID) {
        identifiers.insert(identifier)
    }

    func contains(_ identifier: UUID) -> Bool {
        identifiers.contains(identifier)
    }

    @discardableResult
    func consume(_ identifier: UUID) -> Bool {
        identifiers.remove(identifier) != nil
    }

    func blocks(any candidates: Set<UUID>) -> Bool {
        !identifiers.isDisjoint(with: candidates)
    }
}

private final class PeripheralAttemptDelegate: NSObject, CBPeripheralDelegate {
    weak var owner: BluetoothManager?
    let token: PeripheralAttemptToken

    init(owner: BluetoothManager, token: PeripheralAttemptToken) {
        self.owner = owner
        self.token = token
    }

    func peripheral(
        _ peripheral: CBPeripheral,
        didDiscoverServices error: Error?
    ) {
        owner?.handleServicesDiscovered(
            peripheral,
            token: token,
            error: error
        )
    }

    func peripheral(
        _ peripheral: CBPeripheral,
        didDiscoverCharacteristicsFor service: CBService,
        error: Error?
    ) {
        owner?.handleCharacteristicsDiscovered(
            peripheral,
            service: service,
            token: token,
            error: error
        )
    }

    func peripheral(
        _ peripheral: CBPeripheral,
        didUpdateNotificationStateFor characteristic: CBCharacteristic,
        error: Error?
    ) {
        owner?.handleNotificationState(
            peripheral,
            characteristic: characteristic,
            token: token,
            error: error
        )
    }

    func peripheral(
        _ peripheral: CBPeripheral,
        didUpdateValueFor characteristic: CBCharacteristic,
        error: Error?
    ) {
        owner?.handleUpdatedValue(
            peripheral,
            characteristic: characteristic,
            token: token,
            error: error
        )
    }

    func peripheralIsReady(toSendWriteWithoutResponse peripheral: CBPeripheral) {
        owner?.handlePeripheralWriteReady(peripheral, token: token)
    }
}

private struct PendingConnection {
    let pairIdentity: String
    let left: CBPeripheral
    let right: CBPeripheral
    let generation: Int
}

final class BluetoothManager: NSObject, CBCentralManagerDelegate {
    static let shared = BluetoothManager()

    private var centralManager: CBCentralManager!
    private var channel: FlutterMethodChannel?
    private var pairedDevices: [String: (CBPeripheral?, CBPeripheral?)] = [:]
    private var currentDeviceName: String?
    private var leftPeripheral: CBPeripheral?
    private var rightPeripheral: CBPeripheral?
    private var leftReadCharacteristic: CBCharacteristic?
    private var rightReadCharacteristic: CBCharacteristic?
    private var leftWriteCharacteristic: CBCharacteristic?
    private var rightWriteCharacteristic: CBCharacteristic?
    private var readyIdentifiers: Set<UUID> = []
    private var pendingWrites: [UUID: [Data]] = [:]
    private var connectionGeneration = 0
    private let attemptAuthority = ConnectionAttemptAuthority()
    private let retiredConnections = RetiredConnectionBarrier()
    private var delegateProxies: [UUID: PeripheralAttemptDelegate] = [:]
    private var pendingConnection: PendingConnection?
    private var pendingActivationScheduled = false
    private let pcmConverter = PcmConverter()

    private let uartServiceUUID = CBUUID(
        string: ServiceIdentifiers.uartServiceUUIDString
    )
    private let uartReceiveUUID = CBUUID(
        string: ServiceIdentifiers.uartRXCharacteristicUUIDString
    )
    private let uartWriteUUID = CBUUID(
        string: ServiceIdentifiers.uartTXCharacteristicUUIDString
    )

    var blueInfoSink: FlutterEventSink?
    var blueSpeechSink: FlutterEventSink?

    private override init() {
        super.init()
        centralManager = CBCentralManager(delegate: self, queue: nil)
    }

    func attach(channel: FlutterMethodChannel) {
        self.channel = channel
    }

    func beginAudioSession() {
        pcmConverter.reset()
    }

    func startScan(result: @escaping FlutterResult) {
        guard centralManager.state == .poweredOn else {
            result(
                FlutterError(
                    code: "BluetoothOff",
                    message: "Bluetooth is not powered on",
                    details: nil
                )
            )
            return
        }
        pairedDevices.removeAll()
        centralManager.scanForPeripherals(withServices: nil, options: nil)
        result("Scanning for devices...")
    }

    func stopScan(result: @escaping FlutterResult) {
        centralManager.stopScan()
        result("Scan stopped")
    }

    func connectToDevice(deviceName: String, result: @escaping FlutterResult) {
        centralManager.stopScan()
        guard let pair = pairedDevices[deviceName] else {
            result(
                FlutterError(
                    code: "DeviceNotFound",
                    message: "Device not found",
                    details: nil
                )
            )
            return
        }
        guard let left = pair.0, let right = pair.1 else {
            result(
                FlutterError(
                    code: "PeripheralNotFound",
                    message: "One or both peripherals were not found",
                    details: nil
                )
            )
            return
        }

        let nextGeneration = connectionGeneration + 1
        pendingConnection = nil
        clearConnection(cancelLinks: true, notify: false, reason: "superseded")
        connectionGeneration = nextGeneration
        pendingConnection = PendingConnection(
            pairIdentity: deviceName,
            left: left,
            right: right,
            generation: nextGeneration
        )
        schedulePendingActivationIfReady()
        result("Connecting to \(deviceName)...")
    }

    func disconnectFromGlasses(result: @escaping FlutterResult) {
        pendingConnection = nil
        clearConnection(cancelLinks: true, notify: true, reason: "user_requested")
        result("Disconnected all devices.")
    }

    func sendData(params: [String: Any]) -> Bool {
        guard
            let typedData = params["data"] as? FlutterStandardTypedData,
            !typedData.data.isEmpty,
            expectedAuthorityMatches(params)
        else {
            return false
        }
        return writeData(
            writeData: typedData.data,
            side: params["lr"] as? String
        )
    }

    func centralManager(
        _ central: CBCentralManager,
        didDiscover peripheral: CBPeripheral,
        advertisementData: [String: Any],
        rssi RSSI: NSNumber
    ) {
        guard let name = peripheral.name else { return }
        let components = name.components(separatedBy: "_")
        guard components.count == 4, name.hasPrefix("G") else { return }
        let channelNumber = components[1]
        let key = "Pair_\(channelNumber)"
        var pair = pairedDevices[key] ?? (nil, nil)
        if name.contains("_L_") {
            pair.0 = peripheral
        } else if name.contains("_R_") {
            pair.1 = peripheral
        } else {
            return
        }
        pairedDevices[key] = pair
        guard let left = pair.0, let right = pair.1 else { return }
        channel?.invokeMethod(
            "foundPairedGlasses",
            arguments: [
                "leftDeviceName": left.name ?? "",
                "rightDeviceName": right.name ?? "",
                "channelNumber": channelNumber,
                "pairIdentity": key,
            ]
        )
    }

    func centralManager(
        _ central: CBCentralManager,
        didConnect peripheral: CBPeripheral
    ) {
        if retiredConnections.contains(peripheral.identifier) {
            central.cancelPeripheralConnection(peripheral)
            return
        }
        guard
            let token = attemptAuthority.token(for: peripheral.identifier),
            owns(peripheral, token: token)
        else {
            central.cancelPeripheralConnection(peripheral)
            return
        }
        let proxy = PeripheralAttemptDelegate(owner: self, token: token)
        delegateProxies[peripheral.identifier] = proxy
        peripheral.delegate = proxy
        peripheral.discoverServices([uartServiceUUID])
    }

    func centralManager(
        _ central: CBCentralManager,
        didFailToConnect peripheral: CBPeripheral,
        error: Error?
    ) {
        if retiredConnections.consume(peripheral.identifier) {
            discardRetiredPeripheral(peripheral)
            schedulePendingActivationIfReady()
            return
        }
        guard
            let token = attemptAuthority.token(for: peripheral.identifier),
            owns(peripheral, token: token)
        else {
            return
        }
        handleUnexpectedDisconnect(
            peripheral,
            token: token,
            reason: error?.localizedDescription ?? "connect_failed",
            cancelLink: false
        )
    }

    func centralManager(
        _ central: CBCentralManager,
        didDisconnectPeripheral peripheral: CBPeripheral,
        error: Error?
    ) {
        if retiredConnections.consume(peripheral.identifier) {
            discardRetiredPeripheral(peripheral)
            schedulePendingActivationIfReady()
            return
        }
        guard
            let token = attemptAuthority.token(for: peripheral.identifier),
            owns(peripheral, token: token)
        else {
            return
        }
        handleUnexpectedDisconnect(
            peripheral,
            token: token,
            reason: error?.localizedDescription ?? "link_disconnected",
            cancelLink: false
        )
    }

    func centralManagerDidUpdateState(_ central: CBCentralManager) {
        if central.state != .poweredOn {
            pendingConnection = nil
            clearConnection(
                cancelLinks: false,
                notify: true,
                reason: "bluetooth_\(central.state.rawValue)"
            )
        }
    }

    fileprivate func handleServicesDiscovered(
        _ peripheral: CBPeripheral,
        token: PeripheralAttemptToken,
        error: Error?
    ) {
        guard owns(peripheral, token: token) else { return }
        guard error == nil else {
            handleUnexpectedDisconnect(
                peripheral,
                token: token,
                reason: error!.localizedDescription,
                cancelLink: true
            )
            return
        }
        guard let service = peripheral.services?.first(where: {
            $0.uuid == uartServiceUUID
        }) else {
            handleUnexpectedDisconnect(
                peripheral,
                token: token,
                reason: "uart_service_missing",
                cancelLink: true
            )
            return
        }
        peripheral.discoverCharacteristics(
            [uartReceiveUUID, uartWriteUUID],
            for: service
        )
    }

    fileprivate func handleCharacteristicsDiscovered(
        _ peripheral: CBPeripheral,
        service: CBService,
        token: PeripheralAttemptToken,
        error: Error?
    ) {
        guard owns(peripheral, token: token) else { return }
        guard error == nil else {
            handleUnexpectedDisconnect(
                peripheral,
                token: token,
                reason: error!.localizedDescription,
                cancelLink: true
            )
            return
        }
        guard let characteristics = service.characteristics else {
            handleUnexpectedDisconnect(
                peripheral,
                token: token,
                reason: "uart_characteristics_missing",
                cancelLink: true
            )
            return
        }
        let read = characteristics.first { $0.uuid == uartReceiveUUID }
        let write = characteristics.first { $0.uuid == uartWriteUUID }
        guard let read, let write else {
            handleUnexpectedDisconnect(
                peripheral,
                token: token,
                reason: "uart_characteristics_incomplete",
                cancelLink: true
            )
            return
        }
        switch token.side {
        case .left:
            leftReadCharacteristic = read
            leftWriteCharacteristic = write
        case .right:
            rightReadCharacteristic = read
            rightWriteCharacteristic = write
        }
        peripheral.setNotifyValue(true, for: read)
    }

    fileprivate func handleNotificationState(
        _ peripheral: CBPeripheral,
        characteristic: CBCharacteristic,
        token: PeripheralAttemptToken,
        error: Error?
    ) {
        guard owns(peripheral, token: token) else { return }
        guard error == nil, characteristic.isNotifying else {
            handleUnexpectedDisconnect(
                peripheral,
                token: token,
                reason: error?.localizedDescription ?? "notify_not_enabled",
                cancelLink: true
            )
            return
        }
        markReady(peripheral, token: token)
    }

    fileprivate func handleUpdatedValue(
        _ peripheral: CBPeripheral,
        characteristic: CBCharacteristic,
        token: PeripheralAttemptToken,
        error: Error?
    ) {
        guard owns(peripheral, token: token) else { return }
        guard error == nil, let data = characteristic.value, !data.isEmpty else {
            return
        }
        handleCommand(data: data, peripheral: peripheral, token: token)
    }

    fileprivate func handlePeripheralWriteReady(
        _ peripheral: CBPeripheral,
        token: PeripheralAttemptToken
    ) {
        guard owns(peripheral, token: token) else { return }
        drainWrites(peripheral, token: token)
    }

    private func activate(_ connection: PendingConnection) {
        guard connection.generation == connectionGeneration else { return }
        currentDeviceName = connection.pairIdentity
        leftPeripheral = connection.left
        rightPeripheral = connection.right
        let leftToken = attemptAuthority.begin(
            peripheralID: connection.left.identifier,
            side: .left,
            generation: connection.generation
        )
        let rightToken = attemptAuthority.begin(
            peripheralID: connection.right.identifier,
            side: .right,
            generation: connection.generation
        )
        let leftProxy = PeripheralAttemptDelegate(owner: self, token: leftToken)
        let rightProxy = PeripheralAttemptDelegate(owner: self, token: rightToken)
        delegateProxies[connection.left.identifier] = leftProxy
        delegateProxies[connection.right.identifier] = rightProxy
        connection.left.delegate = leftProxy
        connection.right.delegate = rightProxy
        channel?.invokeMethod(
            "glassesConnecting",
            arguments: [
                "leftDeviceName": connection.left.name ?? "",
                "rightDeviceName": connection.right.name ?? "",
                "generation": connection.generation,
                "pairIdentity": connection.pairIdentity,
            ]
        )
        centralManager.connect(
            connection.left,
            options: [CBConnectPeripheralOptionNotifyOnDisconnectionKey: true]
        )
        centralManager.connect(
            connection.right,
            options: [CBConnectPeripheralOptionNotifyOnDisconnectionKey: true]
        )
    }

    private func schedulePendingActivationIfReady() {
        guard !pendingActivationScheduled else { return }
        pendingActivationScheduled = true
        DispatchQueue.main.async { [weak self] in
            guard let self else { return }
            self.pendingActivationScheduled = false
            guard let pending = self.pendingConnection else { return }
            let identifiers: Set<UUID> = [
                pending.left.identifier,
                pending.right.identifier,
            ]
            guard !self.retiredConnections.blocks(any: identifiers) else {
                return
            }
            self.pendingConnection = nil
            self.activate(pending)
        }
    }

    private func markReady(
        _ peripheral: CBPeripheral,
        token: PeripheralAttemptToken
    ) {
        guard owns(peripheral, token: token) else { return }
        let inserted = readyIdentifiers.insert(peripheral.identifier).inserted
        if inserted {
            let accepted = writeData(
                writeData: Data([0x4d, 0x01]),
                side: token.side.rawValue
            )
            if !accepted {
                readyIdentifiers.remove(peripheral.identifier)
                handleUnexpectedDisconnect(
                    peripheral,
                    token: token,
                    reason: "initialization_write_not_accepted",
                    cancelLink: true
                )
                return
            }
        }
        guard
            let left = leftPeripheral,
            let right = rightPeripheral,
            readyIdentifiers.contains(left.identifier),
            readyIdentifiers.contains(right.identifier),
            token.generation == connectionGeneration,
            let pairIdentity = currentDeviceName
        else {
            return
        }
        channel?.invokeMethod(
            "glassesConnected",
            arguments: [
                "leftDeviceName": left.name ?? "",
                "rightDeviceName": right.name ?? "",
                "status": "ready",
                "left_connected": true,
                "right_connected": true,
                "generation": token.generation,
                "pairIdentity": pairIdentity,
            ]
        )
    }

    private func writeData(writeData: Data, side: String?) -> Bool {
        switch side {
        case "L":
            return enqueueWrite(
                writeData,
                peripheral: leftPeripheral,
                characteristic: leftWriteCharacteristic,
                expectedSide: .left
            )
        case "R":
            return enqueueWrite(
                writeData,
                peripheral: rightPeripheral,
                characteristic: rightWriteCharacteristic,
                expectedSide: .right
            )
        case nil:
            let left = enqueueWrite(
                writeData,
                peripheral: leftPeripheral,
                characteristic: leftWriteCharacteristic,
                expectedSide: .left
            )
            let right = enqueueWrite(
                writeData,
                peripheral: rightPeripheral,
                characteristic: rightWriteCharacteristic,
                expectedSide: .right
            )
            return left && right
        default:
            return false
        }
    }

    private func enqueueWrite(
        _ data: Data,
        peripheral: CBPeripheral?,
        characteristic: CBCharacteristic?,
        expectedSide: GlassesLeg
    ) -> Bool {
        guard
            let peripheral,
            let characteristic,
            let token = attemptAuthority.token(for: peripheral.identifier),
            token.side == expectedSide,
            owns(peripheral, token: token),
            readyIdentifiers.contains(peripheral.identifier)
        else {
            return false
        }
        if peripheral.canSendWriteWithoutResponse {
            peripheral.writeValue(data, for: characteristic, type: .withoutResponse)
            return true
        }
        var queue = pendingWrites[peripheral.identifier] ?? []
        guard queue.count < 128 else { return false }
        queue.append(data)
        pendingWrites[peripheral.identifier] = queue
        return true
    }

    private func drainWrites(
        _ peripheral: CBPeripheral,
        token: PeripheralAttemptToken
    ) {
        guard
            owns(peripheral, token: token),
            let characteristic = writeCharacteristic(for: peripheral, token: token),
            var queue = pendingWrites[peripheral.identifier]
        else {
            return
        }
        while peripheral.canSendWriteWithoutResponse, !queue.isEmpty {
            let data = queue.removeFirst()
            peripheral.writeValue(data, for: characteristic, type: .withoutResponse)
        }
        pendingWrites[peripheral.identifier] = queue.isEmpty ? nil : queue
    }

    private func writeCharacteristic(
        for peripheral: CBPeripheral,
        token: PeripheralAttemptToken
    ) -> CBCharacteristic? {
        guard owns(peripheral, token: token) else { return nil }
        switch token.side {
        case .left:
            return leftWriteCharacteristic
        case .right:
            return rightWriteCharacteristic
        }
    }

    private func handleCommand(
        data: Data,
        peripheral: CBPeripheral,
        token: PeripheralAttemptToken
    ) {
        guard owns(peripheral, token: token) else { return }
        let command = AG_BLE_REQ(rawValue: data[0])
        if command == .BLE_REQ_TRANSFER_MIC_DATA {
            guard data.count == 202 else { return }
            let compressed = data.subdata(in: 2..<data.count)
            guard compressed.count == 200 else { return }
            let pcm = pcmConverter.decode(compressed) as Data
            guard pcm.count == 3_200 else { return }
            guard owns(peripheral, token: token) else { return }
            SpeechStreamRecognizer.shared.appendPCMData(pcm)
            return
        }
        guard let pairIdentity = currentDeviceName else { return }
        blueInfoSink?([
            "type": "Receive",
            "lr": token.side.rawValue,
            "data": data,
            "generation": token.generation,
            "pairIdentity": pairIdentity,
        ])
    }

    private func handleUnexpectedDisconnect(
        _ peripheral: CBPeripheral,
        token: PeripheralAttemptToken,
        reason: String,
        cancelLink: Bool
    ) {
        guard owns(peripheral, token: token) else { return }
        attemptAuthority.retire(token)
        delegateProxies[peripheral.identifier] = nil
        peripheral.delegate = nil
        readyIdentifiers.remove(peripheral.identifier)
        pendingWrites[peripheral.identifier] = nil
        switch token.side {
        case .left:
            leftReadCharacteristic = nil
            leftWriteCharacteristic = nil
        case .right:
            rightReadCharacteristic = nil
            rightWriteCharacteristic = nil
        }
        if cancelLink, peripheral.state != .disconnected {
            retiredConnections.insert(peripheral.identifier)
            centralManager.cancelPeripheralConnection(peripheral)
        }
        channel?.invokeMethod(
            "glassesDisconnected",
            arguments: [
                "leftDeviceName": leftPeripheral?.name ?? "",
                "rightDeviceName": rightPeripheral?.name ?? "",
                "reason": reason,
                "side": token.side.rawValue,
                "left_connected": isReady(.left),
                "right_connected": isReady(.right),
                "generation": token.generation,
                "pairIdentity": currentDeviceName ?? "unselected",
            ]
        )
    }

    private func clearConnection(
        cancelLinks: Bool,
        notify: Bool,
        reason: String
    ) {
        let previousGeneration = connectionGeneration
        let previousPairIdentity = currentDeviceName ?? "unselected"
        let peripherals = [leftPeripheral, rightPeripheral].compactMap { $0 }
        attemptAuthority.retireAll()
        for peripheral in peripherals {
            peripheral.delegate = nil
            delegateProxies[peripheral.identifier] = nil
            if cancelLinks, peripheral.state != .disconnected {
                retiredConnections.insert(peripheral.identifier)
                centralManager.cancelPeripheralConnection(peripheral)
            }
        }
        if notify, !peripherals.isEmpty {
            channel?.invokeMethod(
                "glassesDisconnected",
                arguments: [
                    "leftDeviceName": leftPeripheral?.name ?? "",
                    "rightDeviceName": rightPeripheral?.name ?? "",
                    "reason": reason,
                    "side": "both",
                    "left_connected": false,
                    "right_connected": false,
                    "generation": previousGeneration,
                    "pairIdentity": previousPairIdentity,
                ]
            )
        }
        readyIdentifiers.removeAll()
        pendingWrites.removeAll()
        leftReadCharacteristic = nil
        rightReadCharacteristic = nil
        leftWriteCharacteristic = nil
        rightWriteCharacteristic = nil
        leftPeripheral = nil
        rightPeripheral = nil
        currentDeviceName = nil
    }

    private func owns(
        _ peripheral: CBPeripheral,
        token: PeripheralAttemptToken
    ) -> Bool {
        guard
            token.generation == connectionGeneration,
            token.peripheralID == peripheral.identifier,
            attemptAuthority.owns(token)
        else {
            return false
        }
        switch token.side {
        case .left:
            return peripheral === leftPeripheral
        case .right:
            return peripheral === rightPeripheral
        }
    }

    private func isReady(_ side: GlassesLeg) -> Bool {
        let peripheral = side == .left ? leftPeripheral : rightPeripheral
        guard
            let peripheral,
            let token = attemptAuthority.token(for: peripheral.identifier),
            token.side == side,
            owns(peripheral, token: token)
        else {
            return false
        }
        return readyIdentifiers.contains(peripheral.identifier)
    }

    private func expectedAuthorityMatches(_ params: [String: Any]) -> Bool {
        if let expected = params["expectedGeneration"] as? NSNumber,
           expected.intValue != connectionGeneration {
            return false
        }
        if let expected = params["expectedGeneration"] as? Int,
           expected != connectionGeneration {
            return false
        }
        if let expected = params["expectedPairIdentity"] as? String,
           expected != currentDeviceName {
            return false
        }
        return currentDeviceName != nil
    }

    private func discardRetiredPeripheral(_ peripheral: CBPeripheral) {
        peripheral.delegate = nil
        delegateProxies[peripheral.identifier] = nil
        pendingWrites[peripheral.identifier] = nil
        readyIdentifiers.remove(peripheral.identifier)
    }
}
