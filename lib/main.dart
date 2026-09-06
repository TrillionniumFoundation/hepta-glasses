import 'package:demo_ai_even/ble_manager.dart';
import 'package:demo_ai_even/bootstrap/hepta_bootstrap.dart';
import 'package:demo_ai_even/controllers/evenai_model_controller.dart';
import 'package:demo_ai_even/runtime/audit_checkpoint_authenticator.dart';
import 'package:demo_ai_even/runtime/model_gateway.dart';
import 'package:demo_ai_even/runtime/mutation_authority.dart';
import 'package:demo_ai_even/runtime/privacy_safe_log.dart';
import 'package:demo_ai_even/views/home_page.dart';
import 'package:flutter/material.dart';
import 'package:get/get.dart';

Future<void> main() async {
  WidgetsFlutterBinding.ensureInitialized();
  ModelGatewayBootstrap.configureFromDevelopmentEnvironment();
  SpeechBootstrapBootstrap.configureFromDevelopmentEnvironment();
  BleManager.get();

  try {
    final supportPath = await BleManager.invokeMethod<String>(
      'getApplicationSupportPath',
    );
    if (supportPath == null || supportPath.trim().isEmpty) {
      throw StateError('durable_application_support_path_unavailable');
    }
    await HeptaBootstrap.initialize(
      supportPath,
      checkpointAuthenticator: const PlatformAuditCheckpointAuthenticator(),
      mutationAuthority: const FailClosedMutationAuthorityProvider(),
    );
  } on Object catch (error) {
    PrivacySafeLog.event(
      'runtime_startup_failed',
      fields: <String, Object?>{'error_type': error.runtimeType.toString()},
    );
    runApp(const FailClosedStartupApp());
    return;
  }

  Get.put(EvenaiModelController());
  runApp(const MyApp());
}

class FailClosedStartupApp extends StatelessWidget {
  const FailClosedStartupApp({super.key});

  @override
  Widget build(BuildContext context) => const MaterialApp(
        home: Scaffold(
          body: SafeArea(
            child: Center(
              child: Padding(
                padding: EdgeInsets.all(24),
                child: Text(
                  'Hepta Glasses could not establish durable local state. '
                  'Device and assistant actions remain disabled. Restart the '
                  'application or contact support.',
                  textAlign: TextAlign.center,
                ),
              ),
            ),
          ),
        ),
      );
}

class MyApp extends StatelessWidget {
  const MyApp({super.key});

  @override
  Widget build(BuildContext context) => MaterialApp(
        title: 'Hepta Glasses',
        theme: ThemeData(
          colorScheme: ColorScheme.fromSeed(seedColor: Colors.blue),
          useMaterial3: true,
        ),
        home: const HomePage(),
      );
}
