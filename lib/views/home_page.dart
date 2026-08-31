import 'dart:async';

import 'package:demo_ai_even/ble_manager.dart';
import 'package:demo_ai_even/services/evenai.dart';
import 'package:demo_ai_even/views/even_list_page.dart';
import 'package:demo_ai_even/views/features_page.dart';
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:get/get.dart';

class HomePage extends StatefulWidget {
  const HomePage({super.key});

  @override
  State<HomePage> createState() => _HomePageState();
}

class _HomePageState extends State<HomePage> {
  Timer? _scanTimer;
  bool _isScanning = false;
  String? _connectionError;

  @override
  void initState() {
    super.initState();
    final manager = BleManager.get();
    manager.setMethodCallHandler();
    manager.startListening();
    manager.onStatusChanged = _refreshPage;
  }

  void _refreshPage() {
    if (mounted) {
      setState(() {});
    }
  }

  Future<void> _startScan() async {
    if (_isScanning || BleManager.get().isConnected) {
      return;
    }
    setState(() {
      _isScanning = true;
      _connectionError = null;
    });
    try {
      await BleManager.get().startScan();
      if (!mounted || !_isScanning) {
        return;
      }
      _scanTimer?.cancel();
      _scanTimer = Timer(
        const Duration(seconds: 15),
        () => unawaited(_stopScan()),
      );
    } on PlatformException catch (error) {
      _finishScanWithError(_scanErrorMessage(error.code));
    } on Object {
      _finishScanWithError('Unable to start Bluetooth scanning.');
    }
  }

  String _scanErrorMessage(String code) {
    switch (code) {
      case 'Permission':
        return 'Bluetooth permission is required before glasses can be found.';
      case 'BluetoothOff':
        return 'Turn on Bluetooth before scanning for glasses.';
      default:
        return 'Unable to start Bluetooth scanning ($code).';
    }
  }

  void _finishScanWithError(String message) {
    _scanTimer?.cancel();
    _scanTimer = null;
    if (mounted) {
      setState(() {
        _isScanning = false;
        _connectionError = message;
      });
    } else {
      _isScanning = false;
      _connectionError = message;
    }
  }

  Future<void> _stopScan() async {
    if (!_isScanning) {
      return;
    }
    _scanTimer?.cancel();
    _scanTimer = null;
    try {
      await BleManager.get().stopScan();
    } on Object {
      if (mounted) {
        setState(() {
          _connectionError ??=
              'Bluetooth scanning could not be stopped cleanly.';
        });
      }
    } finally {
      if (mounted) {
        setState(() => _isScanning = false);
      } else {
        _isScanning = false;
      }
    }
  }

  Future<void> _connect(String channel) async {
    await _stopScan();
    if (mounted) {
      setState(() => _connectionError = null);
    }
    try {
      await BleManager.get().connectToGlasses('Pair_$channel');
    } on PlatformException catch (error) {
      if (mounted) {
        setState(() {
          _connectionError =
              'Unable to connect to Pair $channel (${error.code}).';
        });
      }
    } on Object {
      if (mounted) {
        setState(() {
          _connectionError = 'Unable to connect to Pair $channel.';
        });
      }
    }
  }

  Future<void> _disconnect() async {
    try {
      await BleManager.get().disconnectFromGlasses();
    } on PlatformException catch (error) {
      if (mounted) {
        setState(() {
          _connectionError = 'Unable to disconnect cleanly (${error.code}).';
        });
      }
    } on Object {
      if (mounted) {
        setState(() {
          _connectionError = 'Unable to disconnect cleanly.';
        });
      }
    }
  }

  Widget _pairedGlassesList() {
    final glasses = BleManager.get().getPairedGlasses();
    if (glasses.isEmpty) {
      return Expanded(
        child: Center(
          child: Text(
            _isScanning
                ? 'Scanning for a complete left/right G1 pair…'
                : 'Tap the connection card to scan for glasses.',
            textAlign: TextAlign.center,
            style: const TextStyle(color: Colors.grey),
          ),
        ),
      );
    }
    return Expanded(
      child: ListView.separated(
        separatorBuilder: (BuildContext context, int index) =>
            const SizedBox(height: 8),
        itemCount: glasses.length,
        itemBuilder: (BuildContext context, int index) {
          final pair = glasses[index];
          final channel = pair['channelNumber'];
          if (channel == null || channel.isEmpty) {
            return const SizedBox.shrink();
          }
          return Card(
            child: ListTile(
              title: Text('Pair $channel'),
              subtitle: Text(
                'Left: ${pair['leftDeviceName'] ?? 'unknown'}\n'
                'Right: ${pair['rightDeviceName'] ?? 'unknown'}',
              ),
              onTap: () => _connect(channel),
            ),
          );
        },
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    final manager = BleManager.get();
    return Scaffold(
      appBar: AppBar(
        title: const Text('Hepta Glasses'),
        actions: <Widget>[
          if (manager.isConnected)
            IconButton(
              tooltip: 'Disconnect glasses',
              onPressed: _disconnect,
              icon: const Icon(Icons.link_off),
            ),
          IconButton(
            tooltip: 'Features',
            onPressed: () {
              Navigator.of(context).push(
                MaterialPageRoute<void>(
                  builder: (BuildContext context) => const FeaturesPage(),
                ),
              );
            },
            icon: const Icon(Icons.menu),
          ),
        ],
      ),
      body: SafeArea(
        child: Padding(
          padding: const EdgeInsets.fromLTRB(16, 12, 16, 24),
          child: Column(
            children: <Widget>[
              Semantics(
                button: !manager.isConnected,
                label: manager.isConnected
                    ? manager.getConnectionStatus()
                    : 'Scan for a paired left and right G1 device',
                child: InkWell(
                  borderRadius: BorderRadius.circular(8),
                  onTap: manager.isConnected || _isScanning ? null : _startScan,
                  child: Container(
                    width: double.infinity,
                    constraints: const BoxConstraints(minHeight: 100),
                    padding: const EdgeInsets.all(16),
                    decoration: BoxDecoration(
                      color: Colors.white,
                      borderRadius: BorderRadius.circular(8),
                    ),
                    alignment: Alignment.center,
                    child: _isScanning
                        ? const Column(
                            mainAxisSize: MainAxisSize.min,
                            children: <Widget>[
                              CircularProgressIndicator(),
                              SizedBox(height: 12),
                              Text('Scanning…'),
                            ],
                          )
                        : Text(
                            manager.getConnectionStatus(),
                            textAlign: TextAlign.center,
                            style: const TextStyle(fontSize: 16),
                          ),
                  ),
                ),
              ),
              if (_connectionError != null) ...<Widget>[
                const SizedBox(height: 12),
                Semantics(
                  liveRegion: true,
                  child: Text(
                    _connectionError!,
                    textAlign: TextAlign.center,
                    style: TextStyle(
                      color: Theme.of(context).colorScheme.error,
                    ),
                  ),
                ),
              ],
              const SizedBox(height: 16),
              if (!manager.isConnected) _pairedGlassesList(),
              if (manager.isConnected)
                Expanded(
                  child: InkWell(
                    borderRadius: BorderRadius.circular(8),
                    onTap: () {
                      Navigator.of(context).push(
                        MaterialPageRoute<void>(
                          builder: (BuildContext context) =>
                              const EvenAIListPage(),
                        ),
                      );
                    },
                    child: Container(
                      width: double.infinity,
                      decoration: BoxDecoration(
                        color: Colors.white,
                        borderRadius: BorderRadius.circular(8),
                      ),
                      padding: const EdgeInsets.all(16),
                      alignment: Alignment.topCenter,
                      child: SingleChildScrollView(
                        child: StreamBuilder<String>(
                          stream: EvenAI.textStream,
                          initialData:
                              'Press and hold the left TouchBar to start.',
                          builder:
                              (
                                BuildContext context,
                                AsyncSnapshot<String> snapshot,
                              ) => Obx(
                                () => EvenAI.isEvenAISyncing.value
                                    ? const Padding(
                                        padding: EdgeInsets.all(24),
                                        child: CircularProgressIndicator(),
                                      )
                                    : Text(
                                        snapshot.data ??
                                            'No assistant response.',
                                        style: const TextStyle(fontSize: 14),
                                        textAlign: TextAlign.center,
                                      ),
                              ),
                        ),
                      ),
                    ),
                  ),
                ),
            ],
          ),
        ),
      ),
    );
  }

  Future<void> _stopScanSilently() async {
    try {
      await BleManager.get().stopScan();
    } on Object {
      // The widget is already being disposed; native teardown remains best effort.
    }
  }

  @override
  void dispose() {
    _scanTimer?.cancel();
    if (_isScanning) {
      unawaited(_stopScanSilently());
    }
    BleManager.get().onStatusChanged = null;
    super.dispose();
  }
}
