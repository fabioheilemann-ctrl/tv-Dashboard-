package de.kommando.tv;

import android.content.BroadcastReceiver;
import android.content.Context;
import android.content.Intent;

/** Startet das Dashboard nach dem Hochfahren des Fernsehers. */
public class BootReceiver extends BroadcastReceiver {
    @Override
    public void onReceive(Context c, Intent intent) {
        Intent i = new Intent(c, MainActivity.class);
        i.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK);
        try { c.startActivity(i); } catch (Exception ignored) { }
    }
}
