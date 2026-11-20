package de.kommando.tv;

import android.app.Activity;
import android.content.ActivityNotFoundException;
import android.content.Intent;
import android.content.pm.PackageManager;
import android.media.tv.TvContract;
import android.media.tv.TvInputInfo;
import android.media.tv.TvInputManager;
import android.net.Uri;
import android.os.Build;
import android.os.Bundle;
import android.os.Handler;
import android.os.Looper;
import android.view.KeyEvent;
import android.view.View;
import android.view.WindowManager;
import android.webkit.JavascriptInterface;
import android.webkit.WebChromeClient;
import android.webkit.WebResourceError;
import android.webkit.WebResourceRequest;
import android.webkit.WebSettings;
import android.webkit.WebView;
import android.webkit.WebViewClient;
import android.widget.Toast;

import java.util.ArrayList;
import java.util.Collections;
import java.util.List;

/** Zeigt das Dashboard im Vollbild und startet auf Wunsch YouTube, Netflix oder HDMI 1. */
public class MainActivity extends Activity {
    static final String URL = "https://fabioheilemann-ctrl.github.io/tv-Dashboard-/";
    private WebView web;
    private final Handler handler = new Handler(Looper.getMainLooper());

    @Override
    protected void onCreate(Bundle state) {
        super.onCreate(state);
        getWindow().addFlags(WindowManager.LayoutParams.FLAG_FULLSCREEN);
        web = new WebView(this);
        setContentView(web);
        hideBars();

        WebSettings s = web.getSettings();
        s.setJavaScriptEnabled(true);
        s.setDomStorageEnabled(true);
        s.setMediaPlaybackRequiresUserGesture(false);
        s.setLoadWithOverviewMode(true);
        s.setUseWideViewPort(true);
        s.setTextZoom(100);
        s.setSupportZoom(false);
        web.setInitialScale(0);
        web.setBackgroundColor(0xFF06050B);
        web.setLayerType(View.LAYER_TYPE_HARDWARE, null);
        web.setWebChromeClient(new WebChromeClient());
        web.setWebViewClient(new WebViewClient() {
            @Override
            public void onReceivedError(WebView v, WebResourceRequest req, WebResourceError err) {
                // Ohne Netz (z. B. direkt nach dem Einschalten): in 10 s neu versuchen
                if (req.isForMainFrame()) handler.postDelayed(() -> v.loadUrl(URL), 10000);
            }
        });
        web.addJavascriptInterface(new Bridge(), "Kommando");
        web.loadUrl(URL);
        web.requestFocus();
    }

    private void hideBars() {
        getWindow().getDecorView().setSystemUiVisibility(
                View.SYSTEM_UI_FLAG_FULLSCREEN | View.SYSTEM_UI_FLAG_HIDE_NAVIGATION
                        | View.SYSTEM_UI_FLAG_IMMERSIVE_STICKY | View.SYSTEM_UI_FLAG_LAYOUT_STABLE);
    }

    @Override
    protected void onResume() {
        super.onResume();
        hideBars();
        if (web != null) {
            web.onResume();
            web.evaluateJavascript("window.loadData && loadData()", null);
        }
    }

    @Override
    protected void onPause() {
        super.onPause();
        if (web != null) web.onPause();
    }

    @Override
    public void onBackPressed() {
        // Zurueck schliesst ein offenes Detailfenster; die App selbst bleibt offen.
        web.evaluateJavascript("(function(){if(location.hash){history.back();return 1}return 0})()", null);
    }

    @Override
    public boolean dispatchKeyEvent(KeyEvent e) {
        if (e.getKeyCode() == KeyEvent.KEYCODE_BACK && e.getAction() == KeyEvent.ACTION_UP) {
            onBackPressed();
            return true;
        }
        if (e.getKeyCode() == KeyEvent.KEYCODE_BACK) return true;
        return super.dispatchKeyEvent(e);
    }

    private void toast(String msg) {
        handler.post(() -> Toast.makeText(this, msg, Toast.LENGTH_LONG).show());
    }

    private boolean startPackage(String... pkgs) {
        PackageManager pm = getPackageManager();
        for (String p : pkgs) {
            Intent i = pm.getLeanbackLaunchIntentForPackage(p);
            if (i == null) i = pm.getLaunchIntentForPackage(p);
            if (i != null) {
                i.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK);
                startActivity(i);
                return true;
            }
        }
        return false;
    }

    private boolean startHdmi(int port) {
        if (Build.VERSION.SDK_INT < 21) return false;
        TvInputManager tim = (TvInputManager) getSystemService(TV_INPUT_SERVICE);
        if (tim == null) return false;
        List<TvInputInfo> hdmi = new ArrayList<>();
        for (TvInputInfo info : tim.getTvInputList()) {
            if (info.getType() == TvInputInfo.TYPE_HDMI && !info.isHidden(this)) hdmi.add(info);
        }
        if (hdmi.isEmpty()) return false;
        TvInputInfo pick = null;
        for (TvInputInfo info : hdmi) {
            CharSequence label = info.loadLabel(this);
            if (label != null && label.toString().replace(" ", "").toUpperCase().contains("HDMI" + port)) pick = info;
        }
        if (pick == null) {
            Collections.sort(hdmi, (a, b) -> a.getId().compareTo(b.getId()));
            pick = hdmi.get(Math.min(port - 1, hdmi.size() - 1));
        }
        Intent i = new Intent(Intent.ACTION_VIEW, TvContract.buildChannelUriForPassthroughInput(pick.getId()));
        i.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK);
        try {
            startActivity(i);
            return true;
        } catch (ActivityNotFoundException ex) {
            return false;
        }
    }

    class Bridge {
        @JavascriptInterface
        public void open(String app) {
            handler.post(() -> {
                boolean ok;
                switch (app) {
                    case "youtube": ok = startPackage("com.google.android.youtube.tv", "com.google.android.youtube"); break;
                    case "netflix": ok = startPackage("com.netflix.ninja", "com.netflix.mediaclient"); break;
                    case "hdmi1": ok = startHdmi(1); break;
                    default: ok = false;
                }
                if (!ok) toast(app.toUpperCase() + " konnte nicht gestartet werden");
            });
        }

        @JavascriptInterface
        public String version() {
            return "1";
        }
    }
}
