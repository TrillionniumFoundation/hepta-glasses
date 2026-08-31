import CoreBluetooth
import Flutter

final class BluetoothManager: NSObject, CBCentralManagerDelegate, CBPeripheralDelegate {
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
    private var intentionalDisconnects: Set<UUID> = []
    private var pendingWrites: [UUID: [Data]] = [:]
    private var connectionGeneration = 0
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

        clearConnection(cancelLinks: true, notify: false, reason: "superseded")
        connectionGeneration += 1
        currentDeviceName = deviceName
        leftPeripheral = left
        rightPeripheral = right
        left.delegate = self
        right.delegate = self
        channel?.invokeMethod(
            "glassesConnecting",
            arguments: [
                "leftDeviceName": left.name ?? "",
                "rightDeviceName": right.name ?? "",
                "generation": connectionGeneration,
            ]
        )
        centralManager.connect(
            left,
            options: [CBConnectPeripheralOptionNotifyOnDisconnectionKey: true]
        )
        centralManager.connect(
            right,
            options: [CBConnectPeripheralOptionNotifyOnDisconnectionKey: true]
        )
        result("Connecting to \(deviceName)...")
    }

    func disconnectFromGlasses(result: @escaping FlutterResult) {
        clearConnection(cancelLinks: true, notify: true, reason: "user_requested")
        result("Disconnected all devices.")
    }

    func sendData(params: [String: Any]) -> Bool {
        guard
            let typedData = params["data"] as? FlutterStandardTypedData,
            !typedData.data.isEmpty
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
            ]
        )
    }

    func centralManager(
        _ central: CBCentralManager,
        didConnect peripheral: CBPeripheral
    ) {
        guard isSelected(peripheral) else {
            central.cancelPeripheralConnection(peripheral)
            return
        }
        peripheral.delegate = self
        peripheral.discoverServices([uartServiceUUID])
    }

    func centralManager(
        _ central: CBCentralManager,
        didFailToConnect peripheral: CBPeripheral,
        error: Error?
    ) {
        handleUnexpectedDisconnect(
            peripheral,
            reason: error?.localizedDescription ?? "connect_failed"
        )
    }

    func centralManager(
        _ central: CBCentralManager,
        didDisconnectPeripheral peripheral: CBPeripheral,
        error: Error?
    ) {
        pendingWrites[peripheral.identifier] = nil
        readyIdentifiers.remove(peripheral.identifier)
        if intentionalDisconnects.remove(peripheral.identifier) != nil {
            return
        }
        handleUnexpectedDisconnect(
            peripheral,
            reason: error?.localizedDescription ?? "link_disconnected"
        )
    }

    func centralManagerDidUpdateState(_ central: CBCentralManager) {
        if central.state != .poweredOn {
            clearConnection(
                cancelLinks: false,
                notify: true,
                reason: "bluetooth_\(central.state.rawValue)"
            )
        }
    }

    func peripheral(
        _ peripheral: CBPeripheral,
        didDiscoverServices error: Error?
    ) {
        guard error == nil else {
            handleUnexpectedDisconnect(
                peripheral,
                reason: error!.localizedDescription
            )
            return
        }
        guard let service = peripheral.services?.first(where: {
            $0.uuid == uartServiceUUID
        }) else {
            handleUnexpectedDisconnect(peripheral, reason: "uart_service_missing")
            return
        }
        peripheral.discoverCharacteristics(
            [uartReceiveUUID, uartWriteUUID],
            for: service
        )
    }

    func peripheral(
        _ peripheral: CBPeripheral,
        didDiscoverCharacteristicsFor service: CBService,
        error: Error?
    ) {
        guard error == nil else {
            handleUnexpectedDisconnect(
                peripheral,
                reason: error!.localizedDescription
            )
            return
        }
        guard let characteristics = service.characteristics else {
            handleUnexpectedDisconnect(
                peripheral,
                reason: "uart_characteristics_missing"
            )
            return
        }
        let read = characteristics.first { $0.uuid == uartReceiveUUID }
        let write = characteristics.first { $0.uuid == uartWriteUUID }
        guard let read, let write else {
            handleUnexpectedDisconnect(
                peripheral,
                reason: "uart_characteristics_incomplete"
            )
            return
        }
        if peripheral === leftPeripheral {
            leftReadCharacteristic = read
            leftWriteCharacteristic = write
        } else if peripheral === rightPeripheral {
            rightReadCharacteristic = read
            rightWriteCharacteristic = write
        } else {
            return
        }
        peripheral.setNotifyValue(true, for: read)
    }

    func peripheral(
        _ peripheral: CBPeripheral,
        didUpdateNotificationStateFor characteristic: CBCharacteristic,
        error: Error?
    ) {
        guard error == nil, characteristic.isNotifying else {
            handleUnexpectedDisconnect(
                peripheral,
                reason: error?.localizedDescription ?? "notify_not_enabled"
            )
            return
        }
        markReady(peripheral)
    }

    func peripheral(
        _ peripheral: CBPeripheral,
        didUpdateValueFor characteristic: CBCharacteristic,
        error: Error?
    ) {
        guard error == nil, let data = characteristic.value, !data.isEmpty else {
            return
        }
        handleCommand(data: data, peripheral: peripheral)
    }

    func peripheralIsReady(toSendWriteWithoutResponse peripheral: CBPeripheral) {
        drainWrites(peripheral)
    }

    private func markReady(_ peripheral: CBPeripheral) {
        guard isSelected(peripheral) else { return }
        let inserted = readyIdentifiers.insert(peripheral.identifier).inserted
        if inserted {
            let accepted = writeData(
                writeData: Data([0x4d, 0x01]),
                side: peripheral === leftPeripheral ? "L" : "R"
            )
            if !accepted {
                readyIdentifiers.remove(peripheral.identifier)
                handleUnexpectedDisconnect(
                    peripheral,
                    reason: "initialization_write_not_accepted"
                )
                return
            }
        }
        guard
            let left = leftPeripheral,
            let right = rightPeripheral,
            readyIdentifiers.contains(left.identifier),
            readyIdentifiers.contains(right.identifier)
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
                "generation": connectionGeneration,
            ]
        )
    }

    private func writeData(writeData: Data, side: String?) -> Bool {
        switch side {
        case "L":
            return enqueueWrite(
                writeData,
                peripheral: leftPeripheral,
                characteristic: leftWriteCharacteristic
            )
        case "R":
            return enqueueWrite(
                writeData,
                peripheral: rightPeripheral,
                characteristic: rightWriteCharacteristic
            )
        case nil:
            let left = enqueueWrite(
                writeData,
                peripheral: leftPeripheral,
                characteristic: leftWriteCharacteristic
            )
            let right = enqueueWrite(
                writeData,
                peripheral: rightPeripheral,
                characteristic: rightWriteCharacteristic
            )
            return left && right
        default:
            return false
        }
    }

    private func enqueueWrite(
        _ data: Data,
        peripheral: CBPeripheral?,
        characteristic: CBCharacteristic?
    ) -> Bool {
        guard
            let peripheral,
            let characteristic,
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

    private func drainWrites(_ peripheral: CBPeripheral) {
        guard
            let characteristic = writeCharacteristic(for: peripheral),
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
        for peripheral: CBPeripheral
    ) -> CBCharacteristic? {
        if peripheral === leftPeripheral { return leftWriteCharacteristic }
        if peripheral === rightPeripheral { return rightWriteCharacteristic }
        return nil
    }

    private func handleCommand(data: Data, peripheral: CBPeripheral) {
        let command = AG_BLE_REQ(rawValue: data[0])
        if command == .BLE_REQ_TRANSFER_MIC_DATA {
            guard data.count == 202 else { return }
            let compressed = data.subdata(in: 2..<data.count)
            guard compressed.count == 200 else { return }
            let pcm = pcmConverter.decode(compressed) as Data
            guard pcm.count == 3_200 else { return }
            SpeechStreamRecognizer.shared.appendPCMData(pcm)
            return
        }
        blueInfoSink?([
            "type": "Receive",
            "lr": peripheral === leftPeripheral ? "L" : "R",
            "data": data,
            "generation": connectionGeneration,
        ])
    }

    private func handleUnexpectedDisconnect(
        _ peripheral: CBPeripheral,
        reason: String
    ) {
        readyIdentifiers.remove(peripheral.identifier)
        pendingWrites[peripheral.identifier] = nil
        if peripheral === leftPeripheral {
            leftReadCharacteristic = nil
            leftWriteCharacteristic = nil
        } else if peripheral === rightPeripheral {
            rightReadCharacteristic = nil
            rightWriteCharacteristic = nil
        }
        channel?.invokeMethod(
            "glassesDisconnected",
            arguments: [
                "leftDeviceName": leftPeripheral?.name ?? "",
                "rightDeviceName": rightPeripheral?.name ?? "",
                "reason": reason,
                "side": peripheral === leftPeripheral ? "L" : "R",
                "left_connected": leftPeripheral.map {
                    readyIdentifiers.contains($0.identifier)
                } ?? false,
                "right_connected": rightPeripheral.map {
                    readyIdentifiers.contains($0.identifier)
                } ?? false,
                "generation": connectionGeneration,
            ]
        )
    }

    private func clearConnection(
        cancelLinks: Bool,
        notify: Bool,
        reason: String
    ) {
        let peripherals = [leftPeripheral, rightPeripheral].compactMap { $0 }
        if cancelLinks {
            for peripheral in peripherals {
                intentionalDisconnects.insert(peripheral.identifier)
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
                    "generation": connectionGeneration,
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

    private func isSelected(_ peripheral: CBPeripheral) -> Bool {
        peripheral === leftPeripheral || peripheral === rightPeripheral
    }
}
