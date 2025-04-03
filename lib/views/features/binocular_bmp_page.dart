import 'package:demo_ai_even/ble_manager.dart';
import 'package:demo_ai_even/services/features_services.dart';
import 'package:flutter/material.dart';
import 'package:file_picker/file_picker.dart';
import 'dart:io';

class BinocularBmpPage extends StatefulWidget {
  const BinocularBmpPage({super.key});

  @override
  _binocularBmpPageState createState() => _binocularBmpPageState();
}

class _binocularBmpPageState extends State<BinocularBmpPage> {
  File? _leftImage;
  File? _rightImage;
  bool _isUploading = false;

  Future<void> _pickBmpFile(bool isLeft) async {
    if (_isUploading) return;  // Prevent selection during upload
    
    try {
      FilePickerResult? result = await FilePicker.platform.pickFiles(
        type: FileType.custom,
        allowedExtensions: ['bmp'],
        allowMultiple: false,
      );

      if (result != null && result.files.single.path != null) {
        setState(() {
          if (isLeft) {
            _leftImage = File(result.files.single.path!);
          } else {
            _rightImage = File(result.files.single.path!);
          }
        });
      }
    } catch (e) {
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(content: Text('Error picking file: ${e.toString()}')),
      );
    }
  }

  Future<void> _uploadImages() async {
    if (BleManager.get().isConnected == false) {
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(content: Text('Please connect to BLE first')),
      );
      return;
    }

    if (_leftImage == null || _rightImage == null) {
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(content: Text('Please select both left and right images')),
      );
      return;
    }

    setState(() {
      _isUploading = true;
    });

    try {
      await FeaturesServices().sendBinocularBmps(_leftImage!.path, _rightImage!.path);
      
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(content: Text('Images uploaded successfully')),
      );
    } catch (e) {
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(content: Text('Upload failed: ${e.toString()}')),
      );
    } finally {
      setState(() {
        _isUploading = false;
      });
    }
  }

  @override
  Widget build(BuildContext context) => Scaffold(
        appBar: AppBar(
          title: const Text('Binocular Show'),
        ),
        body: Padding(
          padding:
              const EdgeInsets.only(left: 16, right: 16, top: 12, bottom: 44),
          child: Column(
            mainAxisAlignment: MainAxisAlignment.start,
            children: [
              // Left Image Section
              Column(
                children: [
                  GestureDetector(
                    onTap: _isUploading ? null : () => _pickBmpFile(true),
                    child: Container(
                      height: 60,
                      decoration: BoxDecoration(
                        color: Colors.white,
                        borderRadius: BorderRadius.circular(5),
                      ),
                      alignment: Alignment.center,
                      child: Text(
                        "Select Left Image", 
                        style: TextStyle(
                          fontSize: 16,
                          color: _isUploading ? Colors.grey.shade300 : Colors.black,
                        ),
                      ),
                    ),
                  ),
                  const SizedBox(height: 8),
                  if (_leftImage != null)
                    Container(
                      height: 200,
                      decoration: BoxDecoration(
                        border: Border.all(color: Colors.grey.shade200),
                      ),
                      child: Image.file(_leftImage!, fit: BoxFit.contain),
                    ),
                ],
              ),
              const SizedBox(height: 16),

              // Right Image Section
              Column(
                children: [
                  GestureDetector(
                    onTap: _isUploading ? null : () => _pickBmpFile(false),
                    child: Container(
                      height: 60,
                      decoration: BoxDecoration(
                        color: Colors.white,
                        borderRadius: BorderRadius.circular(5),
                      ),
                      alignment: Alignment.center,
                      child: Text(
                        "Select Right Image", 
                        style: TextStyle(
                          fontSize: 16,
                          color: _isUploading ? Colors.grey.shade300 : Colors.black,
                        ),
                      ),
                    ),
                  ),
                  const SizedBox(height: 8),
                  if (_rightImage != null)
                    Container(
                      height: 200,
                      decoration: BoxDecoration(
                        border: Border.all(color: Colors.grey.shade200),
                      ),
                      child: Image.file(_rightImage!, fit: BoxFit.contain),
                    ),
                ],
              ),
              const SizedBox(height: 16),
              
              // Upload Button
              ElevatedButton(
                onPressed: _isUploading ? null : _uploadImages,
                style: ElevatedButton.styleFrom(
                  minimumSize: const Size(double.infinity, 50),
                  backgroundColor: Colors.blue,
                  disabledBackgroundColor: Colors.blue.withOpacity(0.5),
                ),
                child: _isUploading
                    ? const CircularProgressIndicator(color: Colors.white)
                    : const Text('Upload Both Images', style: TextStyle(color: Colors.white, fontSize: 16)),
              ),
            ],
          ),
        ),
      );
}