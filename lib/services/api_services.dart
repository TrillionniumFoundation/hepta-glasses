import 'package:demo_ai_even/runtime/model_gateway.dart';

/// Compatibility facade retained while the legacy UI is migrated to the
/// typed runtime. Provider credentials and provider endpoints are deliberately
/// absent from the mobile application.
class ApiService {
  ApiService({ModelGateway? gateway})
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
