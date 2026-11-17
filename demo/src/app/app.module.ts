import { NgModule, Component } from '@angular/core';
import { BrowserModule } from '@angular/platform-browser';
import { BrowserAnimationsModule } from '@angular/platform-browser/animations';
import { HttpClientModule } from '@angular/common/http';
import { RouterModule } from '@angular/router';

/** Hosts the Sentinel module the way the Pineapple web interface does. */
@Component({
    selector: 'app-root',
    template: '<div class="demo-shell"><router-outlet></router-outlet></div>',
})
export class AppComponent { }

@NgModule({
    declarations: [AppComponent],
    imports: [
        BrowserModule,
        BrowserAnimationsModule,
        HttpClientModule,
        RouterModule.forRoot([{
            path: '',
            loadChildren: () => import('../../../projects/Sentinel/src/lib/Sentinel.module').then((m) => m.SentinelModule),
        }]),
    ],
    bootstrap: [AppComponent],
})
export class AppModule { }
