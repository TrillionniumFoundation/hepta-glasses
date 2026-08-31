import 'dart:async';

import 'package:demo_ai_even/ble_manager.dart';
import 'package:demo_ai_even/services/text_service.dart';
import 'package:flutter/material.dart';

class TextPage extends StatefulWidget {
  const TextPage({super.key});

  @override
  State<TextPage> createState() => _TextPageState();
}

class _TextPageState extends State<TextPage> {
  late final TextEditingController _controller;
  bool _sending = false;

  static const String _testContent = '''Welcome to G1.

You're holding eyewear designed to blend aesthetics, wearability and useful functionality.

Technology should remain available without taking control away from the wearer.

See what matters, when it matters.''';

  @override
  void initState() {
    super.initState();
    _controller = TextEditingController(text: _testContent);
  }

  @override
  void dispose() {
    tfController.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final enabled = BleManager.get().isConnected &&
        _controller.text.trim().isNotEmpty &&
        !_sending;
    return Scaffold(
      appBar: AppBar(title: const Text('Text Transfer')),
      body: Padding(
        padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 12),
        child: Column(
          children: <Widget>[
            Container(
              width: double.infinity,
              height: 300,
              decoration: BoxDecoration(
                color: Colors.white,
                borderRadius: BorderRadius.circular(5),
              ),
              margin: const EdgeInsets.only(bottom: 16),
              padding: const EdgeInsets.all(8),
              child: TextField(
                decoration: const InputDecoration.collapsed(hintText: ''),
                controller: _controller,
                onChanged: (_) => setState(() {}),
                maxLines: null,
              ),
            ),
            GestureDetector(
              onTap: enabled ? _send : null,
              child: Container(
                height: 60,
                decoration: BoxDecoration(
                  color: Colors.white,
                  borderRadius: BorderRadius.circular(5),
                ),
                alignment: Alignment.center,
                child: Text(
                  _sending ? 'Sending…' : 'Send to Glasses',
                  style: TextStyle(
                    color: enabled || _sending ? Colors.black : Colors.grey,
                    fontSize: 16,
                  ),
                ),
              ),
            ),
          ],
        ),
      ),
    );
  }

  Future<void> _send() async {
    setState(() => _sending = true);
    try {
      final success = await TextService.get.startSendText(_controller.text);
      if (mounted && !success) {
        ScaffoldMessenger.of(context).showSnackBar(
          const SnackBar(content: Text('Text transfer was not confirmed.')),
        );
      }
    } on Object {
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          const SnackBar(content: Text('Text transfer failed safely.')),
        );
      }
    } finally {
      if (mounted) {
        setState(() => _sending = false);
      }
    }
  }

  @override
  void dispose() {
    unawaited(TextService.get.stopTextSendingByOS());
    _controller.dispose();
    super.dispose();
  }
}
