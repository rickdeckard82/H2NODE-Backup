export namespace config {
	
	export class Schedule {
	    mode: string;
	    time: string;
	    days: number[];
	    interval_hours: number;
	    catch_up: boolean;
	
	    static createFrom(source: any = {}) {
	        return new Schedule(source);
	    }
	
	    constructor(source: any = {}) {
	        if ('string' === typeof source) source = JSON.parse(source);
	        this.mode = source["mode"];
	        this.time = source["time"];
	        this.days = source["days"];
	        this.interval_hours = source["interval_hours"];
	        this.catch_up = source["catch_up"];
	    }
	}

}

export namespace engine {
	
	export class Component {
	    kind: string;
	    name: string;
	    file?: string;
	    size: number;
	    sha256?: string;
	    plain_size: number;
	    plain_sha256?: string;
	    status: string;
	    message?: string;
	    duration_s: number;
	
	    static createFrom(source: any = {}) {
	        return new Component(source);
	    }
	
	    constructor(source: any = {}) {
	        if ('string' === typeof source) source = JSON.parse(source);
	        this.kind = source["kind"];
	        this.name = source["name"];
	        this.file = source["file"];
	        this.size = source["size"];
	        this.sha256 = source["sha256"];
	        this.plain_size = source["plain_size"];
	        this.plain_sha256 = source["plain_sha256"];
	        this.status = source["status"];
	        this.message = source["message"];
	        this.duration_s = source["duration_s"];
	    }
	}
	export class Item {
	    path: string;
	    is_dir: boolean;
	
	    static createFrom(source: any = {}) {
	        return new Item(source);
	    }
	
	    constructor(source: any = {}) {
	        if ('string' === typeof source) source = JSON.parse(source);
	        this.path = source["path"];
	        this.is_dir = source["is_dir"];
	    }
	}
	export class Progress {
	    phase: string;
	    item: string;
	    index: number;
	    count: number;
	    item_bytes: number;
	    item_total: number;
	
	    static createFrom(source: any = {}) {
	        return new Progress(source);
	    }
	
	    constructor(source: any = {}) {
	        if ('string' === typeof source) source = JSON.parse(source);
	        this.phase = source["phase"];
	        this.item = source["item"];
	        this.index = source["index"];
	        this.count = source["count"];
	        this.item_bytes = source["item_bytes"];
	        this.item_total = source["item_total"];
	    }
	}
	export class Result {
	    run_name: string;
	    // Go type: time
	    started_at: any;
	    // Go type: time
	    finished_at: any;
	    status: string;
	    bytes: number;
	    components: Component[];
	    errors: string[];
	
	    static createFrom(source: any = {}) {
	        return new Result(source);
	    }
	
	    constructor(source: any = {}) {
	        if ('string' === typeof source) source = JSON.parse(source);
	        this.run_name = source["run_name"];
	        this.started_at = this.convertValues(source["started_at"], null);
	        this.finished_at = this.convertValues(source["finished_at"], null);
	        this.status = source["status"];
	        this.bytes = source["bytes"];
	        this.components = this.convertValues(source["components"], Component);
	        this.errors = source["errors"];
	    }
	
		convertValues(a: any, classs: any, asMap: boolean = false): any {
		    if (!a) {
		        return a;
		    }
		    if (a.slice && a.map) {
		        return (a as any[]).map(elem => this.convertValues(elem, classs));
		    } else if ("object" === typeof a) {
		        if (asMap) {
		            for (const key of Object.keys(a)) {
		                a[key] = new classs(a[key]);
		            }
		            return a;
		        }
		        return new classs(a);
		    }
		    return a;
		}
	}

}

export namespace main {
	
	export class ConnectInfo {
	    client_id: string;
	    client_name: string;
	    fingerprint: string;
	
	    static createFrom(source: any = {}) {
	        return new ConnectInfo(source);
	    }
	
	    constructor(source: any = {}) {
	        if ('string' === typeof source) source = JSON.parse(source);
	        this.client_id = source["client_id"];
	        this.client_name = source["client_name"];
	        this.fingerprint = source["fingerprint"];
	    }
	}
	export class UIState {
	    version: string;
	    connected: boolean;
	    server_url: string;
	    client_id: string;
	    client_name: string;
	    fingerprint: string;
	    items: engine.Item[];
	    excludes: string[];
	    schedule: config.Schedule;
	    work_dir: string;
	    start_with_windows: boolean;
	    running: boolean;
	    progress?: engine.Progress;
	    next_run: string;
	    last_success: string;
	    history: engine.Result[];
	    log_path: string;
	
	    static createFrom(source: any = {}) {
	        return new UIState(source);
	    }
	
	    constructor(source: any = {}) {
	        if ('string' === typeof source) source = JSON.parse(source);
	        this.version = source["version"];
	        this.connected = source["connected"];
	        this.server_url = source["server_url"];
	        this.client_id = source["client_id"];
	        this.client_name = source["client_name"];
	        this.fingerprint = source["fingerprint"];
	        this.items = this.convertValues(source["items"], engine.Item);
	        this.excludes = source["excludes"];
	        this.schedule = this.convertValues(source["schedule"], config.Schedule);
	        this.work_dir = source["work_dir"];
	        this.start_with_windows = source["start_with_windows"];
	        this.running = source["running"];
	        this.progress = this.convertValues(source["progress"], engine.Progress);
	        this.next_run = source["next_run"];
	        this.last_success = source["last_success"];
	        this.history = this.convertValues(source["history"], engine.Result);
	        this.log_path = source["log_path"];
	    }
	
		convertValues(a: any, classs: any, asMap: boolean = false): any {
		    if (!a) {
		        return a;
		    }
		    if (a.slice && a.map) {
		        return (a as any[]).map(elem => this.convertValues(elem, classs));
		    } else if ("object" === typeof a) {
		        if (asMap) {
		            for (const key of Object.keys(a)) {
		                a[key] = new classs(a[key]);
		            }
		            return a;
		        }
		        return new classs(a);
		    }
		    return a;
		}
	}

}

