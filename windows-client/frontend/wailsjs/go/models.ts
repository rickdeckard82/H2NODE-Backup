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

export namespace service {
	
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

}

