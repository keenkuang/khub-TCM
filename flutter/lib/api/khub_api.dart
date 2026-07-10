import 'dart:convert';
import 'package:http/http.dart' as http;
import 'package:shared_preferences/shared_preferences.dart';

class KhubApi {
  static const baseUrl = 'http://10.0.2.2:8765'; // Android emulator localhost
  static Future<String?> getToken() async {
    final prefs = await SharedPreferences.getInstance();
    return prefs.getString('khub_token');
  }

  static Future<Map<String, String>> _headers() async {
    final t = await getToken();
    return {'Content-Type': 'application/json',
      if (t != null) 'Authorization': 'Bearer $t'};
  }

  static Future<Map> login(String username, String password) async {
    final r = await http.post(Uri.parse('$baseUrl/auth/login'),
      headers: {'Content-Type': 'application/json'},
      body: jsonEncode({'username': username, 'password': password}));
    final data = jsonDecode(r.body);
    if (r.statusCode == 200) {
      final prefs = await SharedPreferences.getInstance();
      await prefs.setString('khub_token', data['token']);
      await prefs.setString('khub_user', jsonEncode(data['user']));
    }
    return data;
  }

  static Future<Map> get(String path) async {
    final r = await http.get(Uri.parse('$baseUrl$path'), headers: await _headers());
    return jsonDecode(r.body);
  }

  static Future<Map> post(String path, Map body) async {
    final r = await http.post(Uri.parse('$baseUrl$path'),
      headers: await _headers(), body: jsonEncode(body));
    return jsonDecode(r.body);
  }
}
