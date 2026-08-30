import 'package:demo_ai_even/ble_manager.dart';
import 'package:demo_ai_even/controllers/bmp_update_manager.dart';
import 'package:demo_ai_even/controllers/evenai_model_controller.dart';
import 'package:demo_ai_even/runtime/hepta_runtime.dart';
import 'package:demo_ai_even/runtime/model_gateway.dart';
import 'package:demo_ai_even/services/proto.dart';
import 'package:demo_ai_even/utils/utils.dart';
import 'package:demo_ai_even/views/home_page.dart';
import 'package:flutter/material.dart';
import 'package:get/get.dart';

Future<void> main() async {
  WidgetsFlutterBinding.ensureInitialized();
  ModelGatewayBootstrap.configureFromDevelopmentEnvironment();
  BleManager.get();
  final bitmapManager = BmpUpdateManager();
  await HeptaRuntime.initialize(
    displayTextEffect: (DisplayTextCommand command) => Proto.sendEvenAIData(
      command.text,
      newScreen: command.newScreen,
      pos: command.position,
      currentPageNumber: command.currentPageNumber,
      maxPageNumber: command.maxPageNumber,
    ),
    microphoneEffect: (String side) async {
      final (_, success) = await Proto.micOn(lr: side);
      return success;
    },
    exitDeviceModeEffect: Proto.exit,
    notificationWhitelistEffect: Proto.sendNewAppWhiteListJson,
    notificationEffect: (
      Map<String, Object?> notification,
      int notificationId,
    ) =>
        Proto.sendNotify(notification, notificationId),
    bitmapAssetEffect: (String assetPath) async {
      final bytes = await Utils.loadBmpImage(assetPath);
      if (bytes.isEmpty) {
        return false;
      }
      final results = await Future.wait<bool>(<Future<bool>>[
        bitmapManager.updateBmp('L', bytes, seq: 0),
        bitmapManager.updateBmp('R', bytes, seq: 0),
      ]);
      return results.every((bool result) => result);
    },
  );
  Get.put(EvenaiModelController());
  runApp(const MyApp());
}

class MyApp extends StatelessWidget {
  const MyApp({super.key});

  @override
  Widget build(BuildContext context) {
    return MaterialApp(
      title: 'Hepta Glasses',
      theme: ThemeData(
        colorScheme: ColorScheme.fromSeed(seedColor: Colors.blue),
        useMaterial3: true,
      ),
      home: const HomePage(),
    );
  }
}
