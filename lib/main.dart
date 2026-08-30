import 'package:demo_ai_even/ble_manager.dart';
import 'package:demo_ai_even/controllers/evenai_model_controller.dart';
import 'package:demo_ai_even/runtime/hepta_runtime.dart';
import 'package:demo_ai_even/runtime/model_gateway.dart';
import 'package:demo_ai_even/services/proto.dart';
import 'package:demo_ai_even/views/home_page.dart';
import 'package:flutter/material.dart';
import 'package:get/get.dart';

Future<void> main() async {
  WidgetsFlutterBinding.ensureInitialized();
  ModelGatewayBootstrap.configureFromDevelopmentEnvironment();
  BleManager.get();
  await HeptaRuntime.initialize(
    displayTextEffect: (DisplayTextCommand command) => Proto.sendEvenAIData(
      command.text,
      newScreen: command.newScreen,
      pos: command.position,
      currentPageNumber: command.currentPageNumber,
      maxPageNumber: command.maxPageNumber,
    ),
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
