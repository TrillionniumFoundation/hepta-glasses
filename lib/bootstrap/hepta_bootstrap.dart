import 'dart:io';

import 'package:demo_ai_even/controllers/bmp_update_manager.dart';
import 'package:demo_ai_even/runtime/audit_checkpoint_authenticator.dart';
import 'package:demo_ai_even/runtime/audit_journal.dart';
import 'package:demo_ai_even/runtime/device_effect_result.dart';
import 'package:demo_ai_even/runtime/hepta_runtime.dart';
import 'package:demo_ai_even/runtime/mutation_authority.dart';
import 'package:demo_ai_even/services/proto.dart';
import 'package:demo_ai_even/utils/utils.dart';

/// The single mobile composition root for deterministic runtime authority.
///
/// Widgets and feature services consume [HeptaRuntime.current]; they do not
/// construct journals, policy engines, mutation authority, or native effects.
/// Production startup remains fail closed until an authenticated authority
/// provider is injected. The development provider is available only through an
/// explicit compile-time flag.
final class HeptaBootstrap {
  const HeptaBootstrap._();

  static Future<void> initialize(String applicationSupportPath) async {
    final supportPath = applicationSupportPath.trim();
    if (supportPath.isEmpty) {
      throw ArgumentError.value(
        applicationSupportPath,
        'applicationSupportPath',
        'must not be empty',
      );
    }

    final auditJournal = JsonlAuditJournal(
      File('$supportPath/hepta-glasses-runtime/audit.jsonl'),
      checkpointAuthenticator: const PlatformAuditCheckpointAuthenticator(),
    );
    final bitmapManager = BmpUpdateManager();
    const allowDevelopmentAuthority = bool.fromEnvironment(
      'HEPTA_ALLOW_DEVELOPMENT_AUTHORITY',
    );
    final MutationAuthorityProvider mutationAuthority =
        allowDevelopmentAuthority
            ? DevelopmentMutationAuthorityProvider(
                enabled: true,
                subject: 'development-user',
                deviceId: 'development-g1-pair',
                policyHash: 'hepta-edge-policy-development-v1',
              )
            : const FailClosedMutationAuthorityProvider();

    await HeptaRuntime.initialize(
      journal: auditJournal,
      mutationAuthority: mutationAuthority,
      displayTextEffect: (DisplayTextCommand command) =>
          Proto.sendEvenAIDataEffect(
        command.text,
        newScreen: command.newScreen,
        pos: command.position,
        currentPageNumber: command.currentPageNumber,
        maxPageNumber: command.maxPageNumber,
      ),
      microphoneEffect: (String side) async {
        final (_, outcome) = await Proto.micOnDirectEffect(lr: side);
        return outcome;
      },
      exitDeviceModeEffect: Proto.exitEffect,
      notificationWhitelistEffect: Proto.sendNewAppWhiteListEffect,
      notificationEffect: (
        Map<String, Object?> notification,
        int notificationId,
      ) =>
          Proto.sendNotifyEffect(notification, notificationId),
      bitmapAssetEffect: (String assetPath) async {
        final bytes = await Utils.loadBmpImage(assetPath);
        if (bytes.isEmpty) {
          return DeviceEffectResult.rejectedBeforeWrite(
            code: 'bitmap_asset_empty',
            externalId: assetPath,
          );
        }
        final left = await bitmapManager.updateBmpEffect('L', bytes, seq: 0);
        if (!left.committed) {
          return left;
        }
        final right = await bitmapManager.updateBmpEffect('R', bytes, seq: 0);
        return DeviceEffectResult.aggregate(
          <DeviceEffectResult>[left, right],
          externalId: 'bitmap-pair:$assetPath',
          partialCode: 'bitmap_dual_leg_partial_effect_indeterminate',
        );
      },
    );
  }
}
