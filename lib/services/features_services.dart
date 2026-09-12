import 'package:hepta_glasses/runtime/contracts.dart';
import 'package:hepta_glasses/runtime/hepta_runtime.dart';

class FeaturesServices {
  Future<ToolReceipt> sendBmp(String imageUrl) {
    final scope = HeptaRuntime.current.beginEffectScope('bitmap-display');
    return HeptaRuntime.current.displayBitmapAsset(
      scope: scope,
      assetPath: imageUrl,
    );
  }

  Future<ToolReceipt> exitBmp() {
    final scope = HeptaRuntime.current.beginEffectScope('bitmap-exit');
    return HeptaRuntime.current.exitDeviceMode(scope: scope);
  }
}
