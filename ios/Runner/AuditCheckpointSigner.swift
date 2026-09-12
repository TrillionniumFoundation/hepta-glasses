import CryptoKit
import Foundation
import Security

enum AuditCheckpointSignerError: Error {
    case randomGenerationFailed(OSStatus)
    case keychainReadFailed(OSStatus)
    case keychainWriteFailed(OSStatus)
    case invalidStoredKey
}

final class AuditCheckpointSigner {
    static let shared = AuditCheckpointSigner()

    private let service = "org.trillionnium.hepta-glasses.audit-checkpoint"
    private let account = "hmac-sha256-v1"
    private let queue = DispatchQueue(
        label: "org.trillionnium.hepta-glasses.audit-checkpoint"
    )

    private init() {}

    func authenticate(_ payload: Data) throws -> Data {
        guard !payload.isEmpty else {
            throw AuditCheckpointSignerError.invalidStoredKey
        }
        return try queue.sync {
            let keyData = try loadOrCreateKey()
            let key = SymmetricKey(data: keyData)
            let code = HMAC<SHA256>.authenticationCode(
                for: payload,
                using: key
            )
            return Data(code)
        }
    }

    private func loadOrCreateKey() throws -> Data {
        let baseQuery: [String: Any] = [
            kSecClass as String: kSecClassGenericPassword,
            kSecAttrService as String: service,
            kSecAttrAccount as String: account,
        ]
        var readQuery = baseQuery
        readQuery[kSecReturnData as String] = true
        readQuery[kSecMatchLimit as String] = kSecMatchLimitOne

        var result: CFTypeRef?
        let readStatus = SecItemCopyMatching(
            readQuery as CFDictionary,
            &result
        )
        if readStatus == errSecSuccess {
            guard let data = result as? Data, data.count == 32 else {
                throw AuditCheckpointSignerError.invalidStoredKey
            }
            return data
        }
        guard readStatus == errSecItemNotFound else {
            throw AuditCheckpointSignerError.keychainReadFailed(readStatus)
        }

        var bytes = [UInt8](repeating: 0, count: 32)
        let randomStatus = SecRandomCopyBytes(
            kSecRandomDefault,
            bytes.count,
            &bytes
        )
        guard randomStatus == errSecSuccess else {
            throw AuditCheckpointSignerError.randomGenerationFailed(randomStatus)
        }
        let keyData = Data(bytes)
        var addQuery = baseQuery
        addQuery[kSecValueData as String] = keyData
        addQuery[kSecAttrAccessible as String] =
            kSecAttrAccessibleAfterFirstUnlockThisDeviceOnly
        let addStatus = SecItemAdd(addQuery as CFDictionary, nil)
        if addStatus == errSecDuplicateItem {
            // Another call/process won the creation race. Re-read the key.
            return try loadOrCreateKey()
        }
        guard addStatus == errSecSuccess else {
            throw AuditCheckpointSignerError.keychainWriteFailed(addStatus)
        }
        return keyData
    }
}
