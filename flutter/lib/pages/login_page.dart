import 'package:flutter/material.dart';
import '../api/khub_api.dart';

class LoginPage extends StatefulWidget {
  _LoginPageState createState() => _LoginPageState();
}
class _LoginPageState extends State<LoginPage> {
  final _userCtrl = TextEditingController(text: 'admin');
  final _passCtrl = TextEditingController();
  String _error = '';

  void _login() async {
    try {
      final r = await KhubApi.login(_userCtrl.text, _passCtrl.text);
      if (r.containsKey('token'))
        Navigator.pushReplacementNamed(context, '/home');
      else
        setState(() => _error = r['error'] ?? '登录失败');
    } catch (e) {
      setState(() => _error = '连接失败');
    }
  }

  Widget build(BuildContext context) => Scaffold(
    body: Padding(padding: EdgeInsets.all(32),
      child: Column(mainAxisAlignment: MainAxisAlignment.center, children: [
        Text('kHUB', style: Theme.of(context).textTheme.headlineLarge),
        SizedBox(height: 32),
        TextField(controller: _userCtrl, decoration: InputDecoration(labelText: '用户名')),
        SizedBox(height: 16),
        TextField(controller: _passCtrl, obscureText: true, decoration: InputDecoration(labelText: '密码')),
        SizedBox(height: 24),
        FilledButton(onPressed: _login, child: Text('登录')),
        if (_error.isNotEmpty) Padding(padding: EdgeInsets.only(top: 16), child: Text(_error, style: TextStyle(color: Colors.red))),
      ]),
    ),
  );
}
