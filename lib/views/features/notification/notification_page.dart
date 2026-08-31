import 'package:demo_ai_even/ble_manager.dart';
import 'package:demo_ai_even/runtime/contracts.dart';
import 'package:demo_ai_even/runtime/hepta_runtime.dart';
import 'package:demo_ai_even/views/features/notification/notify_model.dart';
import 'package:flutter/material.dart';

class NotificationPage extends StatefulWidget {
  const NotificationPage({super.key});

  @override
  State<NotificationPage> createState() => _NotificationState();
}

class _NotificationState extends State<NotificationPage> {
  final FocusNode _identifierFocus = FocusNode();
  final FocusNode _contentFocus = FocusNode();
  late final TextEditingController _identifierController;
  late final TextEditingController _contentController;
  late String _appWhitelist;
  late String _notificationContent;
  bool _setting = false;
  bool _sending = false;
  int _notificationId = 0;

  @override
  void initState() {
    super.initState();
    final evenModel = NotifyAppModel('com.even.test', 'Even');
    final youtubeModel =
        NotifyAppModel('com.google.android.youtube', 'YouTube');
    _appWhitelist =
        NotifyWhitelistModel(<NotifyAppModel>[evenModel, youtubeModel])
            .toShowJson();
    _identifierController = TextEditingController(text: _appWhitelist);

    _notificationContent = NotifyModel(
      1234567890,
      evenModel.identifier,
      'Even Realities',
      'Notify',
      'This is a notification',
      DateTime.now().millisecondsSinceEpoch,
      'Even',
    ).toJson();
    _contentController = TextEditingController(text: _notificationContent);
  }

  @override
  Widget build(BuildContext context) => Scaffold(
        appBar: AppBar(title: const Text('Notification')),
        body: Padding(
          padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 12),
          child: Column(
            children: <Widget>[
              Container(
                width: double.infinity,
                height: 100,
                decoration: BoxDecoration(
                  color: Colors.white,
                  borderRadius: BorderRadius.circular(5),
                ),
                margin: const EdgeInsets.only(bottom: 16),
                padding: const EdgeInsets.all(8),
                child: TextField(
                  decoration: const InputDecoration.collapsed(hintText: ''),
                  focusNode: _identifierFocus,
                  controller: _identifierController,
                  onChanged: (String value) => _appWhitelist = value,
                  maxLines: null,
                ),
              ),
              _button(
                label: _setting ? 'Setting…' : 'Add to whitelist',
                busy: _setting,
                onTap: _setWhitelist,
              ),
              Container(
                width: double.infinity,
                height: 150,
                margin: const EdgeInsets.symmetric(vertical: 16),
                decoration: BoxDecoration(
                  color: Colors.white,
                  borderRadius: BorderRadius.circular(5),
                ),
                padding: const EdgeInsets.all(8),
                child: TextField(
                  decoration: const InputDecoration.collapsed(hintText: ''),
                  focusNode: _contentFocus,
                  controller: _contentController,
                  onChanged: (String value) => _notificationContent = value,
                  maxLines: null,
                ),
              ),
              _button(
                label: _sending ? 'Sending…' : 'Send notification',
                busy: _sending,
                onTap: _sendNotification,
              ),
            ],
          ),
        ),
      );

  Widget _button({
    required String label,
    required bool busy,
    required Future<void> Function() onTap,
  }) {
    final enabled = BleManager.get().isConnected && !busy;
    return GestureDetector(
      onTap: enabled ? onTap : null,
      child: Container(
        height: 40,
        decoration: BoxDecoration(
          color: Colors.white,
          borderRadius: BorderRadius.circular(5),
        ),
        alignment: Alignment.center,
        child: Text(
          label,
          style: TextStyle(
            color: enabled || busy ? Colors.black : Colors.grey,
            fontSize: 16,
          ),
        ),
      ),
    );
  }

  Future<void> _setWhitelist() async {
    final whitelist = NotifyWhitelistModel.fromJson(_appWhitelist);
    if (whitelist == null) {
      _showMessage('JSON conversion error; check the whitelist and retry.');
      return;
    }
    setState(() => _setting = true);
    try {
      final scope = HeptaRuntime.current.beginEffectScope('notify-whitelist');
      final receipt = await HeptaRuntime.current.setNotificationWhitelist(
        scope: scope,
        document: whitelist.toJson(),
      );
      if (mounted) {
        _report(receipt, 'Whitelist update');
      }
    } on Object {
      _showMessage('Whitelist update failed safely.');
    } finally {
      if (mounted) {
        setState(() => _setting = false);
      }
    }
  }

  Future<void> _sendNotification() async {
    final notification = NotifyModel.fromJson(_notificationContent);
    if (notification == null) {
      _showMessage('JSON conversion error; check the notification and retry.');
      return;
    }
    setState(() => _sending = true);
    try {
      _notificationId = (_notificationId + 1) & 0xff;
      final scope = HeptaRuntime.current.beginEffectScope('notification-send');
      final document = notification.toMap().map<String, Object?>(
            (String key, dynamic value) =>
                MapEntry<String, Object?>(key, value),
          );
      final receipt = await HeptaRuntime.current.sendNotification(
        scope: scope,
        notification: document,
        notificationId: _notificationId,
      );
      if (mounted) {
        _report(receipt, 'Notification');
      }
    } on Object {
      _showMessage('Notification send failed safely.');
    } finally {
      if (mounted) {
        setState(() => _sending = false);
      }
    }
  }

  void _report(ToolReceipt receipt, String operation) {
    if (receipt.status == ToolReceiptStatus.succeeded) {
      return;
    }
    _showMessage(
      '$operation was ${receipt.status.name}; reconciliation may be required.',
    );
  }

  void _showMessage(String message) {
    if (!mounted) {
      return;
    }
    ScaffoldMessenger.of(context)
      ..hideCurrentSnackBar()
      ..showSnackBar(SnackBar(content: Text(message)));
  }

  @override
  void dispose() {
    _identifierFocus.dispose();
    _contentFocus.dispose();
    _identifierController.dispose();
    _contentController.dispose();
    super.dispose();
  }
}
