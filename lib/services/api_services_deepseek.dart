import 'package:demo_ai_even/runtime/model_gateway.dart';

/// Legacy class name kept for source compatibility. The implementation now
/// targets the Hepta model gateway and never embeds a third-party provider key.
class ApiDeepSeekService {
  ApiDeepSeekService({ModelGateway? gateway})
      : _gateway = gateway ?? ModelGatewayRegistry.current;

  final ModelGateway _gateway;

  Future<String> sendChatRequest(String question) async {
    try {
      return await _gateway.answer(question: question);
    } on ModelGatewayException catch (error) {
      return 'AI service unavailable (${error.code}).';
    }
  }
}
