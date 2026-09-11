import 'package:demo_ai_even/ble_manager.dart';
import 'package:demo_ai_even/runtime/contracts.dart';
import 'package:demo_ai_even/services/features_services.dart';
import 'package:flutter/material.dart';

class BmpPage extends StatefulWidget {
  const BmpPage({super.key});

  @override
  State<BmpPage> createState() => _BmpState();
}

class _BmpState extends State<BmpPage> {
  final FeaturesServices _features = FeaturesServices();
  bool _busy = false;

  @override
  Widget build(BuildContext context) => Scaffold(
        appBar: AppBar(title: const Text('BMP')),
        body: Padding(
          padding:
              const EdgeInsets.only(left: 16, right: 16, top: 12, bottom: 44),
          child: Column(
            children: <Widget>[
              _action(
                label: 'BMP 1',
                operation: () => _features.sendBmp('assets/images/image_1.bmp'),
              ),
              const SizedBox(height: 16),
              _action(
                label: 'BMP 2',
                operation: () => _features.sendBmp('assets/images/image_2.bmp'),
              ),
              const SizedBox(height: 16),
              _action(label: 'Exit', operation: _features.exitBmp),
            ],
          ),
        ),
      );

  Widget _action({
    required String label,
    required Future<ToolReceipt> Function() operation,
  }) {
    final enabled = BleManager.get().isConnected && !_busy;
    return GestureDetector(
      onTap: enabled ? () => _run(operation) : null,
      child: Container(
        height: 60,
        decoration: BoxDecoration(
          color: Colors.white,
          borderRadius: BorderRadius.circular(5),
        ),
        alignment: Alignment.center,
        child: Text(
          _busy ? 'Working…' : label,
          style: TextStyle(
            color: enabled || _busy ? Colors.black : Colors.grey,
          ),
        ),
      ),
    );
  }

  Future<void> _run(Future<ToolReceipt> Function() operation) async {
    setState(() => _busy = true);
    try {
      final receipt = await operation();
      if (!mounted) {
        return;
      }
      if (receipt.status != ToolReceiptStatus.succeeded) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(
            content: Text(
              'Device effect requires attention: ${receipt.status.name}',
            ),
          ),
        );
      }
    } on Object {
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          const SnackBar(content: Text('Device operation failed safely.')),
        );
      }
    } finally {
      if (mounted) {
        setState(() => _busy = false);
      }
    }
  }
}
